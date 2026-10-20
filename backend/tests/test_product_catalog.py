from test_auth import login


def test_catalog_matches_demo_policy(client):
    response = client.get('/api/v1/products')
    assert response.status_code == 200
    catalog = response.json()
    assert catalog['catalog_version'] == 'demo-v1'
    products = {item['code']: item for item in catalog['items']}
    assert set(products) == {'working_capital', 'equipment'}
    for code, bounds, documents in [
        ('working_capital', (10_000_000, 500_000_000, 3, 24), ['financial_statement']),
        ('equipment', (30_000_000, 1_000_000_000, 6, 36), ['financial_statement', 'equipment_invoice']),
    ]:
        product = products[code]
        assert tuple(product[key] for key in ('min_amount_kopecks', 'max_amount_kopecks', 'min_term_months', 'max_term_months')) == bounds
        assert product['annual_rate_bps'] == 2400
        assert product['required_document_types'] == documents
        assert product['name'] and product['purpose_description']
        assert type(product['min_amount_kopecks']) is int


def test_company_is_taken_from_session(client):
    user = login(client).json()['user']
    first = client.get('/api/v1/company')
    assert first.status_code == 200
    assert set(first.json()) == {'id', 'inn', 'name', 'industry', 'registered_at'}
    assert first.json()['id'] == user['company_id']
    login(client, 'client2@example.test')
    assert client.get('/api/v1/company').json()['id'] != first.json()['id']
    login(client, 'staff@example.test')
    assert client.get('/api/v1/company').status_code == 403
