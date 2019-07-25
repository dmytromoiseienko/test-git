def create(request):
    """
        Create application in FA.Exchange.

    :param request:
    :return:
    """

    assert request.body_json['type'] is not None, 'type is null'
    assert request.body_json['value'] is not None, 'value is null'
    assert request.body_json['rate'] is not None, 'rate is null'

    keys = ['value', 'rate', ]
    if 'recive_value' in request.body_json:
        keys.append('recive_value')
    for k in keys:
        if not isinstance(request.body_json[k], (int, float)):
            return JsonResponse({'code': -1, 'message': 'wrong {} value'.format(k)})
        if request.body_json[k] <= 0:
            return JsonResponse({'code': -1, 'message': '{} must be more than 0'.format(k)})

    tran_type = ExchangeType.objects.filter(id=int(request.body_json['type'])).first()

    blocked = (151,)
    if not tran_type:
        return JsonResponse({'code': -1, 'message': 'wrong type'})
    if tran_type.sell_type.custom_id in blocked or tran_type.buy_type.custom_id in blocked:
        return JsonResponse({'code': -1, 'message': 'Non-exchangeable type qc'})

    if request.user.no_limit is False and Application.objects.checkout_apps_limit(seller=request.user, type=tran_type.type_app_manager()):
        return JsonResponse({'code': -1,
                             'message': Application.objects.error_limit_msg(type=tran_type.type_app_manager())})

    if request.user.no_limit is False and tran_type.sell_type.custom_id == 150:
        user_status = UserStatuses.objects.filter(user=request.user, is_current=True).first()
        if user_status is None or user_status.status.settings.exchange != StatusSettings.FULL:
            return JsonResponse({'code': -1, 'message': 'No access for current status'})

    if 'recive_value' in request.body_json and request.body_json['recive_value'] != 0:
        if not isinstance(request.body_json['recive_value'], (int, float)):
            return JsonResponse({'code': -1, 'message': 'wrong recive value'})

        if tran_type.sell_type.custom_id == 150:
            rate = request.body_json['value'] / request.body_json['recive_value']
        else:
            rate = request.body_json['recive_value'] / request.body_json['value']

        app_vars = dict(
            sell_value=int(request.body_json['value'] * tran_type.sell_type.coin_coef),
            buy_value=int(request.body_json['recive_value'] * tran_type.buy_type.coin_coef),
            rate=rate
        )
    else:
        handled_variable = Amount2(value=request.body_json.get('value'), rate=request.body_json.get('rate'),
                                   type_id=tran_type.sell_type.custom_id, type_id2=tran_type.buy_type.custom_id)
        app_vars = dict(
            sell_value=handled_variable.amount,
            buy_value=handled_variable.amount_rate,
            rate=handled_variable.rate
        )

    if request.user.no_limit is False and tran_type.checkout_max_rate(rate=app_vars['rate']):
        return JsonResponse({'code': -1, 'message': ExchangerAdminFields.objects.msg_max_rate()})

    if 'email' in request.body_json.keys():
        if not isinstance(request.body_json['email'], str):
            return JsonResponse({'code': -1, 'message': 'wrong email value' })

        if not request.user.flag_address_exchange:
            return JsonResponse({'code': -1, 'message': 'Requared address exchange access'})

        to_user = User.objects.filter(email=request.body_json['email'].lower()).first()
        if to_user is None or to_user.id == request.user.id:
            return JsonResponse({'code': -1, 'message': 'Not found user'})
        status_purchase = None
    else:
        to_user = None
        status_purchase = auto_purchase(
            sell_type=tran_type.buy_type.id,
            buy_type=tran_type.sell_type.id,
            rate_limit=app_vars['rate'],
            user=request.user,
            sell_sum=app_vars['buy_value'],
            buy_sum=app_vars['sell_value'],
            session=request.body_json['session_id']
        )
        if status_purchase[0]['sell'] != app_vars['buy_value']:
            app_vars['buy_value'] = status_purchase[0]['sell']
            app_vars['sell_value'] = status_purchase[0]['buy']

    if app_vars['buy_value'] != 0 and app_vars['sell_value'] != 0:
        np_user = UserNetopay(uid=request.user.uid, wallet=request.user.wallet.name,
                              token=request.body_json.get('session_id'))

        status = np_user.send_qc_to_emitter(app_vars['sell_value'], tran_type.sell_type.custom_id,
                                            po_type='wallet', context='send_qc',
                                            io=ADDRESS if 'email' in request.body_json.keys() else EXCHANGE)
        if status[0]:
            app = Application.objects.create(date=timezone.now(),
                                             value_seller=app_vars['sell_value'],
                                             value_buyer=app_vars['buy_value'],
                                             sell_status_id=1,
                                             rate=app_vars['rate'],
                                             buyer_show=True, seller_show=True,
                                             seller_push_show=False,
                                             sell_wallet_type_id=tran_type.sell_type.id,
                                             buy_wallet_type_id=tran_type.buy_type.id,
                                             wallet_seller_id=request.user.wallet_id,
                                             uid_seller_id=request.user.id, uid_buyer=to_user,
                                             lock=False,
                                             is_address=to_user is not None)

            if request.user.no_limit is False:
                app.rate_selection()
            if not app.is_address:
                from_app_to_robot_app(app.id)  # Robot: App -> R obot

            status[1]['application_id'] = app.id
    else:
        status = True, {"code": 1, "message": "Your request has been satisfied without creating a bid."}

    return JsonResponse(status[1])
