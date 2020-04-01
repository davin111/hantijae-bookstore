from django.contrib.auth import login
from django.contrib.sessions.models import Session

from accounts.models import User

def get_user_from_request(request):
    session_key = request.session.session_key
    if not request.session.session_key:
        request.session.save()
        print("after key:", request.session.session_key)
    try:
        session = Session.objects.get(pk=session_key)
    except Session.DoesNotExist as e:
        print("ERROR:", e)
        return None

    if request.user.is_authenticated:
        user = request.user
        print(f"login user - anonymous: {user.anonymous}")
        if not user.last_session:
            print("session saved")
            user.last_session = session
            user.save()
    else:
        session_user = User.objects.filter(last_session=session)
        if session_user.exists():
            print("session user exists")
            user = session_user.first()
            login(request, user)
        else:
            user = User.objects.create(last_session=session, anonymous=True, username=session_key)
            print("anony user created")
    return user