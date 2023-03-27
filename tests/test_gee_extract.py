"""
To form your assertion statements, you need to refer to the
seeded data in extraction-test-db/setup-test-db.txt
"""


from src.make_parquet import (pull_secrets, make_connection, get_titles, get_table, check_table_in_bucket, index)
from src.set_up.make_secrets import (entry)
import pandas as pd
import pytest
import os
from moto import (mock_secretsmanager, mock_s3)
import boto3


@pytest.fixture(scope='function')
def aws_credentials():
    """Mocked AWS Credentials for moto."""

    os.environ['AWS_ACCESS_KEY_ID'] = 'test'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'test'
    os.environ['AWS_SECURITY_TOKEN'] = 'test'
    os.environ['AWS_SESSION_TOKEN'] = 'test'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture(scope='function')
def premock_secretsmanager(aws_credentials):
    with mock_secretsmanager():
        # yield boto3.client('secretsmanager', region_name='us-east-1')
        yield 'unused string, this is just to prevent mock from closing'


def test_pull_secrets_returns_correct_secrets(premock_secretsmanager):
    entry()
    user, password, database, host, port = pull_secrets()

    assert user == 'project_user_4'
    assert password == 'LC7zJxE3BfvY7p'
    assert database == 'totesys'
    assert host == 'nc-data-eng-totesys-production.chpsczt8h1nu.eu-west-2.rds.amazonaws.com'
    assert port == 5432


def test_make_connection_and_get_titles_returns_correct_table_names__test_env():
    conn = make_connection('config/.env.test')        
    dbcur = conn.cursor()
    tables = get_titles(dbcur)

    expected = (
        ['address'],
        ['counterparty'],
        ['currency'],
        ['department'],
        ['design'],
        ['payment_type'],
        ['payment'],
        ['purchase_order'],
        ['sales_order'],
        ['staff'],
        ['transaction']
    )

    assert tables == expected


def test_get_table_returns_test_db_seeded_data():
    conn = make_connection('config/.env.test')        
    dbcur = conn.cursor()
    # tables = (
    #     ['address'],
    #     ['counterparty'],
    #     ['currency'],
    #     ['department'],
    #     ['design'],
    #     ['payment_type'],
    #     ['payment'],
    #     ['purchase_order'],
    #     ['sales_order'],
    #     ['staff'],
    #     ['transaction']
    # )

    rows, keys = get_table(dbcur, ['address'])
    print(rows)
    print(keys)


@pytest.fixture(scope='function')
def premock_s3(aws_credentials):
    with mock_s3():
        yield boto3.client('s3', region_name='us-east-1')


@pytest.fixture
def mock_bucket(premock_s3):
    premock_s3.create_bucket(
        Bucket='nicebucket1679673428',
        CreateBucketConfiguration={'LocationConstraint': 'eu-west-2'}
    )


def test_check_table_in_bucket__0_existing_keys(mock_bucket):
    tables = (
        ['address'],
        ['counterparty'],
        ['currency'],
        ['department'],
        ['design'],
        ['payment_type'],
        ['payment'],
        ['purchase_order'],
        ['sales_order'],
        ['staff'],
        ['transaction']
    )

    for title in tables:
        assert check_table_in_bucket(title) == False


def test_check_table_in_bucket__some_keys_exist(mock_bucket, premock_s3):
    tables = (
        ['address'],
        ['counterparty'],
        ['currency'],
        ['department'],
        ['design'],
        ['payment_type'],
        ['payment'],
        ['purchase_order'],
        ['sales_order'],
        ['staff'],
        ['transaction']
    )
    
    premock_s3.put_object(
        Body='any text', 
        Bucket='nicebucket1679673428',
        Key='design.parquet'
    )
    premock_s3.put_object(
        Body='any text', 
        Bucket='nicebucket1679673428',
        Key='sales_order.parquet'
    )

    for title in tables:
        if title in [['design'], ['sales_order']]:
            assert check_table_in_bucket(title) == True
        else:
            assert check_table_in_bucket(title) == False


@pytest.mark.skip
def test_whole_extract_function(mock_bucket):
    EXTRACTION_SEED_FOLDER = 'database_access/data/parquet'
    SALES_ORDER_FILE = 'sales_order.parquet'

    # Extract test database into .parquet files.
    index('config/.env.test')
    # Read one table into a DataFrame.
    sales_order_table = pd.read_parquet(f'{EXTRACTION_SEED_FOLDER}/{SALES_ORDER_FILE}')
    
    assert sales_order_table.loc[sales_order_table.sales_order_id == 5][['staff_id']].values[0] == 2