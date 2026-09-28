"""Telegram Desktop HTML 내보내기와 같은 모양의 작은 가짜 파일 두 개. 번호 102·103은 봇 메시지."""
import os

PAGE1 = '''<div class="page_header"><div class="content"><div class="text bold">한티재</div></div></div>
<div class="history">
<div class="message service" id="message-1"><div class="body details">27 September 2026</div></div>
<div class="message default clearfix" id="message100">
<div class="pull_left userpic_wrap"><div class="userpic"></div></div>
<div class="body">
<div class="pull_right date details" title="27 September 2026, 22:14:10">22:14</div>
<div class="from_name">
대표님
</div>
<div class="text">
다음 주 <strong>북토크</strong> 010-1234-5678<br>장소 &amp; 시간
</div>
</div>
</div>
<div class="message default clearfix joined" id="message101">
<div class="body">
<div class="pull_right date details" title="27 September 2026, 22:15:00 UTC+09:00">22:15</div>
<div class="reply_to details">In reply to <a href="#go_to_message100" onclick="return GoToMessage(100)">this message</a></div>
<div class="text">
이어서 씀
</div>
</div>
</div>
<div class="message default clearfix" id="message102">
<div class="body">
<div class="pull_right date details" title="27 September 2026, 22:16:00">22:16</div>
<div class="from_name">
한티재봇
</div>
<div class="text">봇 카드</div>
</div>
</div>
</div>
'''

PAGE2 = '''<div class="history">
<div class="message default clearfix joined" id="message103">
<div class="body">
<div class="pull_right date details" title="27.09.2026 22:17:00">22:17</div>
<div class="media_wrap clearfix">
<div class="media clearfix pull_left media_file">
<div class="fill pull_left"></div>
<div class="body"><div class="title bold">보도자료_010-9999-8888.pdf</div><div class="status details">1 MB</div></div>
</div>
</div>
</div>
</div>
<div class="message default clearfix" id="message104">
<div class="body">
<div class="pull_right date details" title="27 September 2026, 22:18:00">22:18</div>
<div class="from_name">편집장님</div>
<div class="forwarded_from details">Forwarded from 누군가</div>
<div class="reply_to details">In reply to <a href="#go_to_message102" onclick="return GoToMessage(102)">this message</a></div>
<div class="media_wrap clearfix"><div class="media clearfix pull_left media_contact"><div class="fill pull_left"></div>
<div class="body"><div class="title bold">독자 이름</div><div class="status details">+82 10 1234 5678</div></div></div></div>
</div>
</div>
<div class="message default clearfix" id="message105">
<div class="body">
<div class="pull_right date details" title="bad date">x</div>
<div class="from_name">편집장님</div>
<div class="text">망가진 메시지</div>
</div>
</div>
</div>
'''


def write_fixture(folder):
    for name, body in (('messages.html', PAGE1), ('messages2.html', PAGE2)):
        with open(os.path.join(folder, name), 'w', encoding='utf-8') as fh:
            fh.write(body)
