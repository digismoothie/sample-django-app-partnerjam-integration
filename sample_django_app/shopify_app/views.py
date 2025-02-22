from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.apps import apps
from .models import Shop
from shopify.utils import shop_url
from django.utils import timezone
from django.http import HttpResponseRedirect
from django.http import Http404
from datetime import timedelta

from shopify_app.partnerjam import PartnerJamClient

import binascii
import json
import os
import re
import shopify
import requests


class LoginView(View):
    def get(self, request, *args, **kwargs):
        if request.GET.get("shop"):
            return authenticate(request)
        return render(
            request, "shopify_app/login.html", {"app_name": "Sample Django app"}
        )

    def post(self, request):
        return authenticate(request)    


def callback(request):
    params = request.GET.dict()
    shop = params.get("shop")
    partnerjam_token = request.COOKIES.get("partner_jam_token")

    try:
        validate_params(request, params)
        access_token, access_scopes = exchange_code_for_access_token(request, shop)
        shop_record = store_shop_information(access_token, access_scopes, partnerjam_token, shop)
        after_authenticate_jobs(shop, access_token)
        notify_partnerjam(shop_record)
    except ValueError as exception:
        messages.error(request, str(exception))
        return redirect(reverse("login"))

    redirect_uri = build_callback_redirect_uri(request, params)
    return redirect(redirect_uri)

def notify_partnerjam(shop_record):
    if not shop_record.partnerjam_token:
        return
    with shopify.Session.temp(shop_record.shopify_domain, 'unstable', shop_record.shopify_token):
        shopify_shop = shopify.Shop.current()
    data = {
            'myshopify_domain': shopify_shop.myshopify_domain,
            "shopify_id": shopify_shop.id,
            'shop_name': shopify_shop.name,
            'token': shop_record.partnerjam_token,
            'secret': settings.PARTNERJAM_SECRET,
            'test': False,
    }
    PartnerJamClient.send_webhook(**data)


@csrf_exempt
def uninstall(request):
    uninstall_data = json.loads(request.body)
    shop = uninstall_data.get("domain")
    Shop.objects.filter(shopify_domain=shop).delete()
    return HttpResponse(status=204)


# Login helper methods


def authenticate(request):
    try:
        shop = get_sanitized_shop_param(request)
        scopes, redirect_uri, state = build_auth_params(request)
        store_state_param(request, state)
        permission_url = _new_session(shop).create_permission_url(
            scopes, redirect_uri, state
        )
        return redirect(permission_url)
    except ValueError as exception:
        messages.error(request, str(exception))
        return redirect(reverse("login"))


def get_sanitized_shop_param(request):
    sanitized_shop_domain = shop_url.sanitize_shop_domain(
        request.GET.get("shop", request.POST.get("shop"))
    )
    if not sanitized_shop_domain:
        raise ValueError("Shop must match 'example.myshopify.com'")
    return sanitized_shop_domain


def build_auth_params(request):
    scopes = get_configured_scopes()
    redirect_uri = build_redirect_uri()
    state = build_state_param()

    return scopes, redirect_uri, state


def get_configured_scopes():
    return apps.get_app_config("shopify_app").SHOPIFY_API_SCOPES.split(",")


def build_redirect_uri():
    app_url = apps.get_app_config("shopify_app").APP_URL
    callback_path = reverse("callback")
    return "https://{app_url}{callback_path}".format(
        app_url=app_url, callback_path=callback_path
    )


def build_state_param():
    return binascii.b2a_hex(os.urandom(15)).decode("utf-8")


def store_state_param(request, state):
    request.session["shopify_oauth_state_param"] = state


def _new_session(shop_url):
    shopify_api_version = apps.get_app_config("shopify_app").SHOPIFY_API_VERSION
    shopify_api_key = apps.get_app_config("shopify_app").SHOPIFY_API_KEY
    shopify_api_secret = apps.get_app_config("shopify_app").SHOPIFY_API_SECRET

    shopify.Session.setup(api_key=shopify_api_key, secret=shopify_api_secret)
    return shopify.Session(shop_url, shopify_api_version)


# Callback helper methods


def validate_params(request, params):
    validate_state_param(request, params.get("state"))
    if not shopify.Session.validate_params(params):  # Validates HMAC
        raise ValueError("Invalid callback parameters")


def validate_state_param(request, state):
    if request.session.get("shopify_oauth_state_param") != state:
        raise ValueError("Anti-forgery state parameter does not match")

    request.session.pop("shopify_oauth_state_param", None)


def exchange_code_for_access_token(request, shop):
    session = _new_session(shop)
    access_token = session.request_token(request.GET)
    access_scopes = session.access_scopes

    return access_token, access_scopes


def store_shop_information(access_token, access_scopes, partnerjam_token, shop):
    shop_record = Shop.objects.get_or_create(shopify_domain=shop)[0]
    shop_record.shopify_token = access_token
    shop_record.access_scopes = access_scopes
    shop_record.partnerjam_token = partnerjam_token

    shop_record.save()
    return shop_record


def build_callback_redirect_uri(request, params):
    base = request.session.get("return_to", reverse("root_path"))
    return "{base}?shop={shop}".format(base=base, shop=params.get("shop"))


# callback after_authenticate_jobs helper methods


def after_authenticate_jobs(shop, access_token):
    create_uninstall_webhook(shop, access_token)


def create_uninstall_webhook(shop, access_token):
    with shopify_session(shop, access_token):
        app_url = apps.get_app_config("shopify_app").APP_URL
        webhook = shopify.Webhook()
        webhook.topic = "app/uninstalled"
        webhook.address = "https://{host}/uninstall".format(host=app_url)
        webhook.format = "json"
        webhook.save()
        


def shopify_session(shopify_domain, access_token):
    api_version = apps.get_app_config("shopify_app").SHOPIFY_API_VERSION

    return shopify.Session.temp(shopify_domain, api_version, access_token)


def partnerjam_init(request):
    partner_jam_token = request.GET.get("token")
    app_store_url = settings.SHOPIFY_APP_STORE_URL  # replace with your app store url
    expiration = timezone.now() + timedelta(
        days=60,
    )
    
    if not partner_jam_token:
        raise Http404
        
    response = HttpResponseRedirect(app_store_url)
    response.set_cookie(
        "partner_jam_token",
        partner_jam_token,
        expires=expiration,
        httponly=True,
        secure=True,
        samesite="Lax",
    )
    return response

