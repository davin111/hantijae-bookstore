from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from context.models import ContextEntry
from context.record import forget
from intake.models import TelegramChat, WorkerState
from marketing.erp import _deliver, run
from marketing.models import ERPImport, ERPMonthlyReport
from marketing.tests.test_erp import export

NOW = datetime(2026, 10, 17, 3, tzinfo=timezone.utc)


class TG:
    def __init__(self):
        self.sent, self.edited, self.files = [], [], {}
        self.fail_send = self.fail_edit = False

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))
        if self.fail_send:
            raise TimeoutError('unknown outcome')
        return {'message_id': len(self.sent) + 100}

    def edit_text(self, chat_id, message_id, text, **kwargs):
        if self.fail_edit:
            raise TimeoutError('unknown outcome')
        self.edited.append((chat_id, message_id, text))


class ERPWorkflowTest(TestCase):
    def setUp(self):
        TelegramChat.objects.create(chat_id=-123, kind=TelegramChat.REVIEWERS)
        WorkerState.put('mode', 'live')
        WorkerState.put('marketing_mode', 'live')
        WorkerState.put('context_record', True)
        WorkerState.put('erp_mode', 'live')
        WorkerState.put('erp_start_at', '2026-10-01T00:00:00+09:00')
        self.tg = TG()
        self.bot = SimpleNamespace(tg=self.tg)
        self.seq = 0
        self.download = patch('marketing.erp.download', side_effect=lambda tg, fid: tg.files[fid])
        self.download.start()
        self.addCleanup(self.download.stop)

    def entry(self, kind='customer', delta=0, chat=-123, month='2026-09', data=None):
        self.seq += 1
        fid = f'file{self.seq}'
        self.tg.files[fid] = data if data is not None else export(kind, delta=delta, month=month)
        return ContextEntry.objects.create(key=f'tg:{chat}:{self.seq}', source='telegram', origin='live',
            chat_id=chat, message_id=self.seq, at=NOW + timedelta(seconds=self.seq), media='document',
            media_name=('거래처 집계 현황.xlsx' if kind == 'customer' else '제품별 집계 현황.xlsx'), file_id=fid)

    def tick(self, minutes=1):
        run(self.bot, NOW + timedelta(minutes=minutes))

    def pair(self, delta=0):
        return self.entry(delta=delta), self.entry('product', delta=delta)

    def test_receipt_pair_and_repeat_only_one_report(self):
        self.pair()
        self.tick()
        report = ERPMonthlyReport.objects.get()
        self.assertEqual(report.state, 'ready')
        self.assertIn('3,000원', report.text)
        self.assertIn('조회 조건', report.text)
        self.assertNotIn('전산망 순판매 0권', report.text)
        self.assertEqual(len(self.tg.sent), 1)
        self.pair()
        self.tick(2)
        self.assertEqual(len(self.tg.sent), 1)
        self.assertEqual(len(self.tg.edited), 0)
        self.assertEqual(ERPImport.objects.count(), 4)

    def test_waiting_then_complete_edits_same_message(self):
        self.entry()
        self.tick()
        self.assertIn('제품별', self.tg.sent[0][1])
        self.entry('product')
        self.tick(2)
        self.assertEqual(len(self.tg.sent), 1)
        self.assertEqual(self.tg.edited[-1][1], 101)
        self.assertIn('순출고', self.tg.edited[-1][2])

    def test_revision_requires_both_new_inputs_and_does_not_add(self):
        self.pair()
        self.tick()
        self.entry(delta=1)
        self.tick(2)
        report = ERPMonthlyReport.objects.get()
        self.assertEqual(report.state, 'waiting')
        self.assertIn('수정', report.text)
        self.entry('product', delta=1)
        self.tick(3)
        report.refresh_from_db()
        self.assertEqual(report.state, 'ready')
        self.assertEqual(report.result['totals']['net_amount'], 4000)
        self.assertEqual(len(self.tg.sent), 1)

    def test_mismatch_is_withheld_until_replacements_agree(self):
        self.entry()
        self.entry('product', delta=1)
        self.tick()
        self.assertEqual(ERPMonthlyReport.objects.get().state, 'blocked')
        self.assertNotIn('순출고 3권', self.tg.sent[0][1])
        self.entry(delta=1)
        self.tick(2)
        self.assertEqual(ERPMonthlyReport.objects.get().state, 'ready')

    def test_months_and_chats_do_not_mix(self):
        self.entry()
        self.entry('product', chat=-456)
        self.entry('product', month='2026-06')
        self.tick()
        self.assertEqual(ERPImport.objects.count(), 2)
        self.assertEqual(ERPMonthlyReport.objects.filter(state='ready').count(), 0)

    def test_edited_document_uses_new_file_id(self):
        customer, product = self.pair()
        self.tick()
        self.tg.files['replacement'] = export(delta=1)
        customer.file_id, customer.edited_at = 'replacement', NOW + timedelta(minutes=2)
        customer.save()
        self.tick(3)
        self.assertEqual(ERPMonthlyReport.objects.get().state, 'waiting')
        self.entry('product', delta=1)
        self.tick(4)
        self.assertEqual(ERPMonthlyReport.objects.get().result['totals']['net_qty'], 4)

    def test_uncertain_initial_send_is_not_retried(self):
        self.pair()
        self.tg.fail_send = True
        self.tick()
        self.tick(20)
        self.assertEqual(len(self.tg.sent), 1)
        self.assertEqual(ERPMonthlyReport.objects.get().delivery_state, 'uncertain')

    def test_interrupted_first_send_is_not_retried(self):
        self.pair()
        self.tick()
        ERPMonthlyReport.objects.update(message_id=None, delivery_state='sending', delivered_hash='')
        self.tick(20)
        self.assertEqual(len(self.tg.sent), 1)
        self.assertEqual(ERPMonthlyReport.objects.get().delivery_state, 'uncertain')

    def test_known_message_edit_can_retry(self):
        self.entry()
        self.tick()
        self.entry('product')
        self.tg.fail_edit = True
        self.tick(2)
        self.tg.fail_edit = False
        self.tick(20)
        self.assertEqual(len(self.tg.sent), 1)
        self.assertEqual(len(self.tg.edited), 1)
        self.assertEqual(ERPMonthlyReport.objects.get().delivery_state, 'sent')

    def test_disabled_and_quiet_hours_do_not_send(self):
        self.pair()
        WorkerState.put('erp_mode', 'off')
        self.tick()
        self.assertEqual(ERPImport.objects.count(), 0)
        WorkerState.put('erp_mode', 'live')
        run(self.bot, NOW.replace(hour=14))
        self.assertFalse(self.tg.sent)
        self.tick(2)
        self.assertEqual(len(self.tg.sent), 1)

    def test_marketing_admin_only_never_delivers_to_review_room(self):
        self.pair()
        WorkerState.put('marketing_mode', 'admin_only')
        self.tick()
        self.assertEqual(ERPImport.objects.count(), 0)
        self.assertFalse(self.tg.sent)

    def test_invalid_file_is_explained_once(self):
        self.entry(data=b'bad file')
        self.tick()
        self.tick(20)
        self.assertEqual(len(self.tg.sent), 1)
        self.assertIn('읽지 못', self.tg.sent[0][1])

    def test_forget_and_source_deletion_remove_derived_numbers(self):
        customer, product = self.pair()
        self.tick()
        forget(-123, customer.message_id)
        self.tick(2)
        self.assertEqual(ERPImport.objects.get(entry=customer).payload, {})
        self.assertEqual(ERPMonthlyReport.objects.get().result, {})
        self.assertIn('지워', ERPMonthlyReport.objects.get().text)
        product.delete()
        self.tick(3)
        self.assertEqual(ERPMonthlyReport.objects.get().result, {})

    def test_download_retry_uses_durable_input(self):
        self.pair()
        with patch('marketing.erp.download', side_effect=TimeoutError):
            self.tick()
        self.assertEqual(ERPImport.objects.filter(status='retry').count(), 2)
        self.tick(20)
        self.assertEqual(ERPMonthlyReport.objects.get().state, 'ready')

    def test_forget_during_download_cannot_restore_numbers(self):
        c, p = self.pair()
        def downloading(tg, fid):
            if fid == c.file_id:
                forget(c.chat_id, c.message_id)
            return tg.files[fid]
        with patch('marketing.erp.download', side_effect=downloading):
            self.tick()
        item = ERPImport.objects.get(entry=c)
        self.assertEqual((item.status, item.payload), ('forgotten', {}))

    def test_stale_report_cannot_send_numbers_after_forget(self):
        c, p = self.pair()
        run(self.bot, NOW.replace(hour=14))
        stale = ERPMonthlyReport.objects.get()
        WorkerState.put('erp_mode', 'off')
        forget(c.chat_id, c.message_id)
        self.assertEqual(ERPMonthlyReport.objects.get().result, {})
        _deliver(stale, self.tg, NOW + timedelta(days=1))
        self.assertFalse(any('순출고 3권' in text for _, text, _ in self.tg.sent))

    def test_invalid_new_file_cannot_fall_back_to_old_valid(self):
        self.entry()
        self.entry(data=b'broken replacement')
        self.entry('product')
        self.tick()
        self.assertEqual(ERPMonthlyReport.objects.get().state, 'blocked')

    def test_batch_limit_does_not_pair_before_newer_pending_file(self):
        self.pair()
        for _ in range(6):
            self.entry()
        self.entry(data=b'broken replacement')
        self.tick()
        self.assertFalse(ERPMonthlyReport.objects.filter(state='ready').exists())

    def test_edit_time_takes_precedence_over_original_message_time(self):
        c, p = self.pair()
        self.tick()
        self.entry(delta=1)
        self.entry('product', delta=2)
        self.tg.files['latest'] = export(delta=2)
        c.file_id, c.edited_at = 'latest', NOW + timedelta(minutes=5)
        c.save()
        self.tick(6)
        self.assertEqual(ERPMonthlyReport.objects.get().result['totals']['net_qty'], 5)

    def test_workbook_metadata_changes_do_not_change_report_revision(self):
        self.pair()
        self.tick()
        def metadata(ws):
            ws.parent.properties.creator = 'another ERP workstation'
        self.entry(data=export(change=metadata))
        self.entry('product', data=export('product', change=metadata))
        self.tick(2)
        self.assertEqual(ERPMonthlyReport.objects.get().revision, 1)
        self.assertFalse(self.tg.edited)

    def test_fixed_edit_does_not_deliver_old_error_notice(self):
        c = self.entry(data=b'broken')
        self.entry('product')
        run(self.bot, NOW.replace(hour=14))
        self.tg.files['fixed'] = export()
        c.file_id, c.edited_at = 'fixed', NOW + timedelta(hours=14)
        c.save()
        run(self.bot, NOW + timedelta(days=1))
        self.assertEqual(ERPMonthlyReport.objects.get().state, 'ready')
        self.assertFalse(any('읽지 못했어요' in text for _, text, _ in self.tg.sent))

    def test_changed_month_in_original_message_withholds_previous_month(self):
        c, p = self.pair()
        self.tick()
        self.tg.files['different-month'] = export(month='2026-06')
        c.file_id, c.edited_at = 'different-month', NOW + timedelta(minutes=2)
        c.save()
        self.tick(3)
        report = ERPMonthlyReport.objects.get(month='2026-09')
        self.assertEqual((report.state, report.result), ('blocked', {}))

    def test_health_shows_uncertain_delivery_and_scan_failure(self):
        from ops.health import evaluate
        self.pair()
        self.tg.fail_send = True
        self.tick()
        row = next(r for r in evaluate(NOW + timedelta(minutes=2)) if r.key == 'erp')
        self.assertEqual(row.state, 'warn')
        self.assertIn('발송 결과 확인', row.reason)
        ERPMonthlyReport.objects.all().delete()
        WorkerState.put('marketing_error_erp', '2026-10-17')
        row = next(r for r in evaluate(NOW + timedelta(minutes=2)) if r.key == 'erp')
        self.assertEqual(row.state, 'warn')
        self.assertIn('marketing_error_erp', row.reason)

    def test_worker_dispatches_erp_without_changing_monthly_watermark(self):
        from marketing.tasks import _run_due
        WorkerState.put('bnk_last_monthly', '2026-09')
        self.pair()
        self.bot.marketing = SimpleNamespace(mode=lambda: 'live')
        # Stop immediately after this real scheduled call; other jobs have their own tests.
        from marketing.erp import run as real_run
        def dispatched(bot, now):
            real_run(bot, now)
            raise KeyboardInterrupt()
        with patch('marketing.erp.run', side_effect=dispatched), self.assertRaises(KeyboardInterrupt):
            _run_due(SimpleNamespace(bot=self.bot), NOW + timedelta(minutes=1))
        self.assertEqual(ERPMonthlyReport.objects.get().state, 'ready')
        self.assertEqual(WorkerState.get('bnk_last_monthly'), '2026-09')
