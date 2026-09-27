from django.conf import settings
from django.shortcuts import render
from django.templatetags.static import static

from web import catalog, site_info


def absolute_url(url: str) -> str:
    if not url:
        return ''
    return url if url.startswith(('http://', 'https://')) else settings.SITE_URL.rstrip('/') + url


def page_meta(path, *, title=None, description=None, image=None, og_type='website', noindex=False, extra=()):
    return {
        'title': f'{title} — {site_info.SITE_NAME}' if title else site_info.SITE_NAME,
        'og_title': title or site_info.SITE_NAME,
        'description': description or site_info.SITE_DESCRIPTION,
        'image': absolute_url(image) or absolute_url(static('web/og-default.png')),
        'url': absolute_url(path),
        'og_type': og_type,
        'noindex': noindex,
        'extra': list(extra),
    }


def render_page(request, template, context, *, meta, nav_active=None, nav_series=None, search_query='', status=200):
    ctx = {
        'meta': meta,
        'nav_active': nav_active,
        'nav_series': catalog.public_series() if nav_series is None else nav_series,
        'search_query': search_query,
        'site': site_info,
        'naver_analytics_id': getattr(settings, 'NAVER_ANALYTICS_ID', ''),
    }
    ctx.update(context)
    return render(request, template, ctx, status=status)
