import pytest
import os
from moto import (mock_secretsmanager, mock_s3)
import boto3
from pathlib import Path
from dotenv import load_dotenv
import json
from src.extract import (
    extract_lambda_handler,
    make_connection
)
from src.transform import transform_lambda_handler
from src.load import load_lambda_handler


@pytest.fixture(scope='function')
def aws_credentials():
    """Mocks AWS Credentials for moto."""
    os.environ['AWS_ACCESS_KEY_ID'] = 'test'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'test'
    os.environ['AWS_SECURITY_TOKEN'] = 'test'
    os.environ['AWS_SESSION_TOKEN'] = 'test'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture(scope='function')
def premock_secretsmanager(aws_credentials):
    """Patches any boto3 secretsmanager in this and imported modules."""

    with mock_secretsmanager():
        yield boto3.client('secretsmanager', region_name='us-east-1')
        # yield 'unused string, this is just to prevent mock from closing'


@pytest.fixture(scope='function')
def premock_s3(aws_credentials):
    """Patches any boto3 s3 in this and imported modules."""

    with mock_s3():
        yield boto3.client('s3', region_name='us-east-1')


@pytest.fixture
def mock_bucket(premock_s3):
    """Uses the patched boto3 s3 to create a mock bucket."""

    premock_s3.create_bucket(
        Bucket='scrumptious-squad-in-data-testmock',
        CreateBucketConfiguration={'LocationConstraint': 'eu-west-2'}
    )

    premock_s3.create_bucket(
        Bucket='scrumptious-squad-pr-data-testmock',
        CreateBucketConfiguration={'LocationConstraint': 'eu-west-2'}
    )


@pytest.fixture
def create_warehouse_secrets(premock_secretsmanager):
    load_dotenv(dotenv_path=Path('config/.env.test_warehouse'))
    premock_secretsmanager.create_secret(
        Name='warehouse_secrets',
        SecretString=json.dumps({
            'host': os.getenv('host'),
            'user': os.getenv('user'),
            'password': os.getenv('password'),
            'database': os.getenv('database'),
            'schema': os.getenv('schema')
        })
    )

    # response = premock_secretsmanager.get_secret_value(SecretId='warehouse_secrets')
    # secrets_text = json.loads(response["SecretString"])
    # print(secrets_text)


def test_updating_an_existing_row(create_warehouse_secrets, premock_s3, mock_bucket):
    """
    Changes an existing row and tests if a new row is created in the warehouse.
    """

    # Execute ETL once with the default seed Totesys database
    extract_lambda_handler({'dotenv_path_string': 'config/.env.test'})
    transform_lambda_handler(None, None)
    response = load_lambda_handler({
        "secret_id": "warehouse_secrets",
        "bucket_prefix": "scrumptious-squad-pr-data-"
    }, None)

    # Check that the loading was successful
    assert response['statusCode'] == 200
    assert response['body'] == 'Data loaded into warehouse successfully'

    # Update an existing entry in the seed Totesys database
    conn = make_connection('config/.env.test')
    dbcur = conn.cursor()
    query_string = '''UPDATE payment
                      SET payment_amount = 50.00, last_updated = '2023-02-02 02:22:22'
                      WHERE payment_id = 3;
                   '''
    dbcur.execute(query_string)

    # Execute ETL once with the updated Totesys database
    extract_lambda_handler({'dotenv_path_string': 'config/.env.test'})
    transform_lambda_handler(None, None)
    response = load_lambda_handler({
        "secret_id": "warehouse_secrets",
        "bucket_prefix": "scrumptious-squad-pr-data-"
    }, None)

    # Check that the loading was successful
    assert response['statusCode'] == 200
    assert response['body'] == 'Data loaded into warehouse successfully'

    # # Get full bucket name from a prefix
    # bucketname = get_bucket_name('scrumptious-squad-in-data-')
    # # Get the response JSON from listing an S3 bucket's contents
    # response = get_file_info_in_bucket(bucketname)
    # # Get the data from .parquets in an S3 bucket as DataFrames
    # sales_order_df = get_parquet('sales_order', bucketname, response)

    # # Test number of columns
    # assert sales_order_df.shape[1] == 12
    # # Test number of rows
    # print(sales_order_df)
    # assert sales_order_df.shape[0] == 2
    # # Test specific cells
    # assert sales_order_df.loc[sales_order_df.sales_order_id == 7][[
    #     'currency_id']].values[0] == 2
    # assert sales_order_df.loc[sales_order_df.sales_order_id == 7][[
    #     'agreed_delivery_date']].values[0] == '2023-09-09'
    # assert sales_order_df.loc[sales_order_df.sales_order_id == 8][[
    #     'last_updated']].values[0] == pd.Timestamp(2023, 3, 3, 8, 45)
    # assert sales_order_df.loc[sales_order_df.sales_order_id == 8][[
    #     'design_id']].values[0] == 7
    # assert sales_order_df.loc[sales_order_df.sales_order_id == 8][[
    #     'unit_price']].values[0] == 5.00
