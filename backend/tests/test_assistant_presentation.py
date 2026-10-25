import json

from app.assistant.schemas import Source


def test_prompt_formats_money_and_rates_without_mutating_public_sources():
    from app.assistant.presentation import prompt_sources
    data = {'amount_kopecks': 200_000_000, 'payment_terms': {
        'monthly_payment_kopecks': 7_930_665, 'annual_rate_bps': 2400,
        'upfront_fee_kopecks': 0}, 'probability': 0.125, 'note': 'Два документа'}
    original = Source(id='application:request', title='Запрос', text=json.dumps(data), version='2')
    shown = prompt_sources([original])[0]
    assert shown['id'] == original.id and shown['version'] == original.version
    values = json.loads(shown['text'])
    assert values['amount_rubles'] == '2 000 000 ₽'
    assert values['payment_terms']['monthly_payment_rubles'] == '79 306,65 ₽'
    assert values['payment_terms']['annual_rate_percent'] == '24%'
    assert values['payment_terms']['upfront_fee_rubles'] == '0 ₽'
    assert values['probability'] == 0.125
    assert json.loads(original.text) == data
    assert '_kopecks' not in shown['text'] and '_bps' not in shown['text']


def test_prompt_money_preserves_large_values_and_negative_averages():
    from app.assistant.presentation import prompt_sources
    data = {'amount_kopecks': 9_007_199_254_740_991,
            'available_flow_kopecks': '-333333.333333333333', 'monthly_debt_kopecks': None}
    source = Source(id='calculation', title='Расчёт', text=json.dumps(data), version='1')
    values = json.loads(prompt_sources([source])[0]['text'])
    assert values['amount_rubles'] == '90 071 992 547 409,91 ₽'
    assert values['available_flow_rubles'] == '-3 333,33 ₽'
    assert values['monthly_debt_rubles'] is None


def test_prompt_leaves_knowledge_and_free_text_untouched():
    from app.assistant.presentation import prompt_sources
    sources = [Source(id='docs', title='Документы', text='Нужны финансовая отчётность и счёт.', version='1'),
               Source(id='request', title='Описание', text=json.dumps({'description': 'Я написал 100 копеек'}), version='1')]
    shown = prompt_sources(sources)
    assert shown[0] == sources[0].model_dump()
    assert json.loads(shown[1]['text'])['description'] == 'Я написал 100 копеек'
