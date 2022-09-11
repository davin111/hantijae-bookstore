from django.contrib.auth import login
from django.contrib.sessions.models import Session

from accounts.models import User


def get_session(request):
    session_key = request.session.session_key
    if not request.session.session_key:
        request.session.save()
    try:
        session = Session.objects.get(pk=session_key)
        return session
    except Session.DoesNotExist as e:
        return None


def get_user_from_request(request):
    session = get_session(request)

    if request.user.is_authenticated:
        user = request.user
        if not user.last_session:
            if session:
                user.last_session = session
                user.save()
        return user
    elif session:
        session_user = User.objects.filter(last_session=session)
        if session_user.exists():
            user = session_user.first()
            login(request, user)
        else:
            user = User.objects.create(last_session=session, anonymous=True, username=request.session.session_key)
        return user
    return None
