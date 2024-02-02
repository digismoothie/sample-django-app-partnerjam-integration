from __future__ import annotations

from decimal import Decimal
from typing import cast
from urllib.parse import urljoin

import requests
from django.conf import settings


class PartnerJamClient:
    _domain = 'https://be-app.partnerjam.com/'
    _webhook_path = "webhooks/installation-confirm/"
    _discount_path = "api/v1/discount-check/"

    @classmethod
    def _is_active(cls) -> bool:
        return bool(cls._domain)

    @classmethod
    def send_webhook(
        cls,
        token: str,
        shopify_id: int,
        shop_name: str,
        myshopify_domain: str,
        secret: str,
        test: bool,
    ) -> None:
        if not cls._is_active():
            return

        if not token:
            return

        url = urljoin(cast(str, cls._domain), cls._webhook_path)

        response = requests.post(
            url,
            json={
                "token": token,
                "shopify_id": shopify_id,
                "shop_name": shop_name,
                "myshopify_domain": myshopify_domain,
                "secret": secret,
                "test": test,
            },
            timeout=5,
        )
        response.raise_for_status()

    @classmethod
    def get_discount(cls, token: str) -> Decimal | None:
        if not cls._is_active():
            return None

        if not token:
            return None

        url = urljoin(cast(str, cls._domain), cls._discount_path)
        response = requests.get(
            url,
            params={
                "token": token,
            },
            timeout=3,
        )
        response.raise_for_status()
        response_json = response.json()
        discount_value = response_json.get("discount")

        if discount_value is not None:
            discount = Decimal(discount_value)

            if discount < Decimal(0) or discount > Decimal(100):
                raise ValueError("Unexpected value. Got {response_json} as the response")

            return discount
        else:
            return None
