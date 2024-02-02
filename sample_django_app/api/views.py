from django.http import JsonResponse
from shopify_app.decorators import session_token_required
from shopify_app.partnerjam import PartnerJamClient
from shopify_app.models import Shop

import shopify


@session_token_required
def products(request):
    products = shopify.Product.find()

    return JsonResponse({'products': [p.to_dict() for p in products]})

@session_token_required
def orders(request):
    orders = shopify.Order.find(status='any')

    return JsonResponse({'orders': [o.to_dict() for o in orders]})


@session_token_required
def subscription(request):
    full_price = 10
    plan_name = 'Standard plan'
    shopify_shop = shopify.Shop.current()
    shop_record = Shop.objects.get(shopify_domain=shopify_shop.myshopify_domain)
    discount = PartnerJamClient.get_discount(shop_record.partnerjam_token)
    print(discount, 'discount')
    if discount:
        price = full_price * ((100 - discount) / 100)
        plan = f"{plan_name} - {discount}% discount"
    else:
        price = full_price
        plan = plan_name
    charge = shopify.RecurringApplicationCharge.create(
            {
                "name": plan,
                "price": price,
                "return_url": request.build_absolute_uri('/'),
                "trial_days": 3,
                "test": True,
            }
        )

    return charge.confirmation_url