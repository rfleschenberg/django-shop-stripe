# -*- coding: utf-8 -*-
from django.core.exceptions import ImproperlyConfigured
from django.conf import settings
from django.conf.urls import patterns, url
from django.http import HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.utils.translation import ugettext_lazy as _

from shop.util.decorators import on_method, order_required

import stripe

from .forms import CardForm


class StripeException(Exception):
    pass


class StripeBackend(object):

    """A django-shop payment backend for the Stripe service.
    """
    backend_name = _("Stripe")
    url_namespace = "stripe"
    template = "shop_stripe/payment.html"
    form_class = CardForm

    def __init__(self, shop):
        self.shop = shop
        self.private_key = self.get_stripe_private_key()
        self.public_key = self.get_stripe_public_key()
        self.currency = self.get_currency()

    def get_urls(self):
        return patterns(
            '',
            url(r'^$', self.stripe_payment_view, name='stripe')
        )

    def get_success_url(self):
        try:
            return self.success_url
        except AttributeError:
            return self.shop.get_finished_url()

    def get_form_class(self):
        return self.form_class

    def get_stripe_private_key(self):
        try:
            return settings.SHOP_STRIPE_PRIVATE_KEY
        except AttributeError:
            raise ImproperlyConfigured(
                'You must define the SHOP_STRIPE_PRIVATE_KEY setting')

    def get_stripe_public_key(self):
        try:
            return settings.SHOP_STRIPE_PUBLISHABLE_KEY
        except AttributeError:
            raise ImproperlyConfigured(
                'You must define the SHOP_STRIPE_PUBLISHABLE_KEY setting')

    def get_currency(self):
        return getattr(settings, 'SHOP_STRIPE_CURRENCY', 'usd')

    def get_description(self, request):
        if request.user.is_authenticated:
            return request.user.email
        return 'guest customer'

    def charge_card(self, token, amount, description):
        stripe.api_key = self.get_stripe_private_key()
        try:
            stripe_result = stripe.Charge.create(card=token,
                                                 currency=self.currency,
                                                 amount=amount,
                                                 description=description)
        except stripe.CardError as e:
            raise StripeException(e.message)
        return stripe_result['id']

    @on_method(order_required)
    def stripe_payment_view(self, request):
        form_class = self.get_form_class()
        error = None
        if request.method == 'POST':
            form = form_class(request.POST)
            order = self.shop.get_order(request)
            order_id = self.shop.get_order_unique_id(order)
            amount = str(int(self.shop.get_order_total(order) * 100))
            description = self.get_description(request)

            token = request.POST.get('stripeToken')
            if not token:
                return HttpResponseBadRequest('stripeToken not set')

            try:
                tx_id = self.charge_card(token, amount, description)
            except StripeException as e:
                error = e
            else:
                self.shop.confirm_payment(
                    self.shop.get_order_for_id(order_id),
                    amount,
                    tx_id,
                    self.backend_name
                )
                return redirect(self.get_success_url())
        else:
            form = form_class()
        return render(request, self.template, {
            'form': form,
            'error': error,
            'STRIPE_PUBLISHABLE_KEY': self.public_key,
        })
