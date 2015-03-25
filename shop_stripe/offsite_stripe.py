# -*- coding: utf-8 -*-

"""django-shop payment backend for the Stripe service."""

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

    """Thrown when Stripe fails to charge the card for any reason"""
    pass


class StripeBackend(object):

    """
    This is the backend class that contains the server-side code to connect
    django-shop to Stripe.

    Subclasses can override attributes and methods of this class to customize
    its behaviour.
    """
    backend_name = _("Stripe")
    url_namespace = "stripe"
    template = "shop_stripe/payment.html"
    form_class = CardForm
    success_url = None

    def __init__(self, shop):
        self.shop = shop
        self.private_key = self.get_stripe_private_key()
        self.public_key = self.get_stripe_public_key()
        self.currency = self.get_currency()

    def get_urls(self):
        """Return the urls for this backend"""
        return patterns(
            '',
            url(r'^$', self.stripe_payment_view, name='stripe')
        )

    def get_success_url(self):
        """Return the success url

           If the ``success_url`` attribute is not None, return that. Otherwise,
           return the value returned by the payment API's ``get_finished_url()``
           method.
        """
        if self.success_url:
            return self.success_url
        else:
            return self.shop.get_finished_url()

    def get_form_class(self):
        """Return the form class.

           Defaults to the ``form_class`` attribute.
        """
        return self.form_class

    def get_stripe_private_key(self):
        """Get the Stripe private API key from the settings."""
        try:
            return settings.SHOP_STRIPE_PRIVATE_KEY
        except AttributeError:
            raise ImproperlyConfigured(
                'You must define the SHOP_STRIPE_PRIVATE_KEY setting')

    def get_stripe_public_key(self):
        """Get the Stripe public key from the settings."""
        try:
            return settings.SHOP_STRIPE_PUBLISHABLE_KEY
        except AttributeError:
            raise ImproperlyConfigured(
                'You must define the SHOP_STRIPE_PUBLISHABLE_KEY setting')

    def get_currency(self):
        """Get the Stripe currency from the settings."""
        return getattr(settings, 'SHOP_STRIPE_CURRENCY', 'usd')

    def get_description(self, request):
        """Get a description for the customer to pass to Stripe.

           If the user is logged in, return the user's ``email`` attribute.
           Otherwise, return ``'guest_customer'`` (possibly translated).
        """
        if request.user.is_authenticated():
            return request.user.email
        return unicode(_('guest customer'))

    def charge_card(self, token, amount, description):
        """Try to charge the card identified by ``token`` using Stripe.

        On success, return the Stripe transaction id.
        On failure, raise ``StripeException``, containing the error message from
        Stripe.
        """
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
        """The payment view

        For GET requests, display an instance of ``form_class`` rendered with
        ``template_name``.
        For POST requests, try to charge the card with the amount for the
        current order using the provided Stripe token.
        """
        form_class = self.get_form_class()
        order = self.shop.get_order(request)
        order_id = self.shop.get_order_unique_id(order)
        amount = self.shop.get_order_total(order)
        currency = self.currency
        context = {
            'error': None,
            'STRIPE_PUBLISHABLE_KEY': self.public_key,
            'amount': amount,
            'currency': currency,
        }
        if request.method == 'POST':
            form = form_class(request.POST)
            description = self.get_description(request)
            stripe_amount = str(int(amount * 100))

            token = request.POST.get('stripeToken')
            if not token:
                return HttpResponseBadRequest('stripeToken not set')

            try:
                tx_id = self.charge_card(token, stripe_amount, description)
            except StripeException as e:
                context['error'] = e
            else:
                self.shop.confirm_payment(
                    self.shop.get_order_for_id(order_id),
                    stripe_amount,
                    tx_id,
                    self.backend_name
                )
                return redirect(self.get_success_url())
        else:
            form = form_class()
        context['form'] = form
        return render(request, self.template, context)
