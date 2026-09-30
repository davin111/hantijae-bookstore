from datetime import date, datetime, timedelta

from django.test import TestCase

from intake.models import WorkerState
from marketing import notion_blocks as nb
from marketing import notion_sync as ns
from marketing.messages import OPEN, POSTED
from marketing.models import Briefing, Draft, Proposal
from marketing.tests.fakes import FakeNotion, FakeTG, http_error, make_book
from marketing.timeutil import KST

NOW = datetime(2026, 10, 5, 9, 30, tzinfo=KST)


class Host:
    def __init__(self, notion):
        self.notion, self.notes = notion, []

    def notify_admin(self, text):
        self.notes.append(text)


def briefing(book, n=2):
    b = Briefing.objects.create(week_start=date(2026, 10, 5), chat_id=-200, message_id=900, sent_at=NOW)
    ps = []
    for i in range(1, n + 1):
        p = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=book, briefing=b, headline=f'항목 {i}',
                                    reason='이유', rank=i, status=Proposal.SHOWN)
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body=f'글 {i}\n\n#한티재')
        ps.append(p)
    b.shown = [p.id for p in ps]
    b.save()
    return b, ps


class NotionSyncTest(TestCase):
    def setUp(self):
        WorkerState.put(ns.SWITCH, 'on')
        WorkerState.put(ns.DS, 'ds1')
        self.fake, self.book = FakeNotion(), make_book()
        self.host = Host(self.fake)

    def page(self, b):
        return ns.ensure_page(self.fake, ns.brief_target(b, '허브 글'), NOW)

    def box_of(self, proposal):
        return Draft.objects.filter(proposal=proposal).order_by('-version').first().notion['box']

    def test_client_for_follows_switch_and_data_source(self):
        self.assertIs(ns.client_for(self.host), self.fake)
        WorkerState.put(ns.SWITCH, 'off')
        self.assertIsNone(ns.client_for(self.host))
        self.assertEqual(ns.switch('on'), 'marketing_notion=on')
        self.assertIn('marketing_notion=on', ns.status_line())

    def test_ensure_page_builds_the_page_and_records_every_block(self):
        b, ps = briefing(self.book)
        url = self.page(b)
        b.refresh_from_db()
        self.assertEqual((url, b.notion['state'], b.notion['url']), (b.notion['url'], 'done', url))
        page = self.fake.pages[b.notion['page']]
        self.assertEqual(page['ds'], 'ds1')
        self.assertEqual(page['properties']['진행']['rich_text'][0]['text']['content'], '남음 2')
        for p in ps:
            p.refresh_from_db()
            self.assertEqual(self.fake.text_of(p.notion['heading']).split('. ')[1], p.headline)
            d = p.drafts.get()
            self.assertEqual(nb.read_box(self.fake.children(d.notion['box']), d.notion['title']), ('', d.body))
        self.assertEqual(self.page(b), url)  # 두 번 만들지 않는다
        self.assertEqual(self.fake.calls.count('create_page'), 1)

    def test_half_built_page_goes_to_trash_and_waits(self):
        b, ps = briefing(self.book)
        self.fake.fail['append_children'] = RuntimeError('노션 오류')
        with self.assertRaises(RuntimeError):
            self.page(b)
        b.refresh_from_db()
        self.assertEqual((b.notion['state'], b.notion['tries'], b.notion['page']), ('pending', 1, ''))
        self.assertTrue(all(pg['in_trash'] for pg in self.fake.pages.values()))
        self.assertEqual([d.pk for d in Draft.objects.all() if d.notion], [])  # 휴지통 페이지의 상자를 가리키지 않는다

    def test_refresh_rewrites_headings_and_progress(self):
        b, ps = briefing(self.book)
        self.page(b)
        Proposal.objects.filter(pk=ps[0].pk).update(status=Proposal.ACTED)
        ns.refresh(self.fake, ns.target_of(Proposal.objects.get(pk=ps[0].pk)))
        ps[0].refresh_from_db()
        self.assertEqual(self.fake.text_of(ps[0].notion['heading']), '✅ 1. 항목 1')
        b.refresh_from_db()
        props = self.fake.pages[b.notion['page']]['properties']
        self.assertEqual(props['진행']['rich_text'][0]['text']['content'], '✅ 1 · 남음 1')

    def test_current_picks_up_a_notion_edit_as_a_new_version(self):
        b, ps = briefing(self.book)
        self.page(b)
        self.fake.edit(self.fake.kids[self.box_of(ps[0])][0], '글 1 고침\n\n#한티재')  # 상자 안 첫 블록 = 본문
        d, note = ns.current(self.fake, ps[0], Draft.INSTAGRAM)
        self.assertEqual((d.version, d.origin, d.body, note), (2, Draft.NOTION, '글 1 고침\n\n#한티재', 'notion'))
        self.assertEqual(d.notion, d.parent.notion)
        again, note = ns.current(self.fake, ps[0], Draft.INSTAGRAM)
        self.assertEqual((again.pk, note), (d.pk, ''))  # 같은 글이면 새 판을 또 만들지 않는다

    def test_formatting_only_changes_are_not_edits(self):
        b, ps = briefing(self.book)
        self.page(b)
        self.fake.edit(self.fake.kids[self.box_of(ps[0])][0], '글 1  \n\n#한티재' + chr(0xA0))
        self.assertEqual(ns.current(self.fake, ps[0], Draft.INSTAGRAM)[1], '')

    def test_deleted_or_empty_box_falls_back(self):
        b, ps = briefing(self.book)
        self.page(b)
        self.fake.edit(self.fake.kids[self.box_of(ps[0])][0], '   ')
        d, note = ns.current(self.fake, ps[0], Draft.INSTAGRAM)
        self.assertEqual((d.version, note), (1, 'empty'))
        self.fake.remove(self.box_of(ps[1]))
        d, note = ns.current(self.fake, ps[1], Draft.INSTAGRAM)
        self.assertEqual((d.version, note), (1, 'empty'))
        self.assertEqual(Draft.objects.count(), 2)

    def test_read_errors_fall_back_and_tell_the_admin_once_a_day(self):
        b, ps = briefing(self.book)
        self.page(b)
        for _ in range(2):
            self.fake.fail['children'] = http_error(502)
            self.assertEqual(ns.current(self.fake, ps[0], Draft.INSTAGRAM, host=self.host, now=NOW)[1], '')
        self.assertEqual(len(self.host.notes), 1)

    def test_read_notice_failure_never_reaches_the_caller(self):
        b, ps = briefing(self.book)
        self.page(b)

        class BadHost(Host):
            def notify_admin(self, text):
                raise RuntimeError('텔레그램 오류')

        self.fake.fail['children'] = http_error(502)
        d, note = ns.current(self.fake, ps[0], Draft.INSTAGRAM, host=BadHost(self.fake), now=NOW)
        self.assertEqual((d.version, note), (1, ''))

    def test_refresh_keeps_going_past_a_missing_heading_then_raises(self):
        b, ps = briefing(self.book)
        self.page(b)
        Proposal.objects.filter(pk__in=[p.pk for p in ps]).update(status=Proposal.ACTED)
        self.fake.fail['update_block'] = RuntimeError('지워진 제목')
        with self.assertRaises(RuntimeError):
            ns.refresh(self.fake, ns.target_of(Proposal.objects.get(pk=ps[0].pk)))
        ps[1].refresh_from_db()
        self.assertEqual(self.fake.text_of(ps[1].notion['heading']), '✅ 2. 항목 2')
        b.refresh_from_db()
        props = self.fake.pages[b.notion['page']]['properties']
        self.assertEqual(props['진행']['rich_text'][0]['text']['content'], '✅ 2')

    def test_no_box_means_no_read(self):
        b, ps = briefing(self.book)
        d, note = ns.current(self.fake, ps[0], Draft.INSTAGRAM)
        self.assertEqual((d.version, note, self.fake.calls), (1, '', []))
        self.assertEqual(ns.current(None, ps[0], Draft.INSTAGRAM)[0].version, 1)

    def test_append_version_adds_a_box_under_the_item_and_relabels_the_old_one(self):
        b, ps = briefing(self.book)
        self.page(b)
        first = ps[0].drafts.get()
        new = Draft.objects.create(proposal=ps[0], channel=Draft.INSTAGRAM, body='둘째', version=2, parent=first,
                                   origin=Draft.REWRITE)
        self.assertTrue(ns.append_version(self.fake, new, '짧게 해 주세요'))
        new.refresh_from_db()
        heading = Proposal.objects.get(pk=ps[0].pk).notion['heading']
        self.assertEqual(self.fake.kids[heading][-1], new.notion['box'])
        self.assertEqual(self.fake.text_of(self.fake.kids[heading][-2]), '고친 글 2 · 요청: "짧게 해 주세요"')
        self.assertEqual(self.fake.text_of(first.notion['box']), nb.OLD_BOX_LABEL)
        self.assertEqual(ns.current(self.fake, ps[0], Draft.INSTAGRAM), (new, ''))

    def test_missing_append_is_retried_on_the_next_read(self):
        b, ps = briefing(self.book)
        self.page(b)
        first = ps[0].drafts.get()
        new = Draft.objects.create(proposal=ps[0], channel=Draft.INSTAGRAM, body='둘째', version=2, parent=first)
        d, note = ns.current(self.fake, ps[0], Draft.INSTAGRAM)
        new.refresh_from_db()
        self.assertEqual((d.pk, note), (new.pk, ''))
        self.assertTrue(new.notion.get('box'))

    def test_kit_page_uses_a_heading_per_channel(self):
        p = Proposal.objects.create(kind=Proposal.KIT, book=self.book, headline='h', caution='조심',
                                    chat_id=-200, message_id=800)
        for ch in (Draft.BLOG, Draft.INSTAGRAM, Draft.LINKS):
            Draft.objects.create(proposal=p, channel=ch, title='제목' if ch == Draft.BLOG else '', body=f'{ch} 글')
        ns.ensure_page(self.fake, ns.kit_target(p, '카드 글', date(2026, 10, 5)), NOW)
        p.refresh_from_db()
        self.assertEqual(set(p.notion['headings']), {Draft.BLOG, Draft.INSTAGRAM, Draft.LINKS})
        blog = p.drafts.get(channel=Draft.BLOG)
        self.assertEqual(nb.read_box(self.fake.children(blog.notion['box']), blog.notion['title']), ('제목', 'blog 글'))
        self.assertEqual(self.fake.pages[p.notion['page']]['properties']['이름']['title'][0]['text']['content'],
                         f'『{self.book.title}』 홍보 자료')

    def test_midweek_items_share_one_page(self):
        ps = [Proposal.objects.create(kind=Proposal.NOW, book=self.book, headline=f'n{i}', rank=i) for i in (1, 2)]
        for p in ps:
            Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='글')
        ns.ensure_page(self.fake, ns.now_target(ps, '주중 글', date(2026, 10, 1)), NOW)
        pages = {Proposal.objects.get(pk=p.pk).notion['page'] for p in ps}
        self.assertEqual(len(pages), 1)

    def test_retry_pending_builds_and_adds_the_telegram_button(self):
        b, ps = briefing(self.book)
        self.fake.fail['create_page'] = RuntimeError('잠깐 오류')
        with self.assertRaises(RuntimeError):
            self.page(b)
        tg = FakeTG()
        self.assertEqual(ns.retry_pending(self.host, tg, NOW + timedelta(minutes=5)), 0)  # 10분이 안 됐다
        self.assertEqual(ns.retry_pending(self.host, tg, NOW + timedelta(minutes=11)), 1)
        b.refresh_from_db()
        self.assertEqual(b.notion['state'], 'done')
        rows = tg.sent('markup')[0]['buttons']['inline_keyboard']
        self.assertEqual(rows[-1][0]['url'], b.notion['url'])

    def test_retry_pending_gives_up_after_a_week(self):
        b, ps = briefing(self.book)
        self.fake.fail['create_page'] = RuntimeError('오류')
        with self.assertRaises(RuntimeError):
            self.page(b)
        ns.retry_pending(self.host, FakeTG(), NOW + timedelta(days=8))
        b.refresh_from_db()
        self.assertEqual(b.notion['state'], 'failed')
        self.assertEqual(len(self.host.notes), 1)

    def test_retry_pending_waits_in_quiet_hours_and_when_off(self):
        b, ps = briefing(self.book)
        self.fake.fail['create_page'] = RuntimeError('오류')
        with self.assertRaises(RuntimeError):
            self.page(b)
        self.assertEqual(ns.retry_pending(self.host, FakeTG(), datetime(2026, 10, 5, 22, 0, tzinfo=KST)), 0)
        WorkerState.put(ns.SWITCH, 'off')
        self.assertEqual(ns.retry_pending(self.host, FakeTG(), NOW + timedelta(hours=1)), 0)
