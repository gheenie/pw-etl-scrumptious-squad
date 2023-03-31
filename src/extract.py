import pg8000
import pandas as pd
import bisect
import boto3
import json
from botocore.exceptions import ClientError
from io import BytesIO
import os
from dotenv import load_dotenv
from pathlib import Path
import logging

 

logger = logging.getLogger('MyLogger')
logger.setLevel(logging.INFO)

def pull_secrets():
    
    secret_name = 'source_DB'     
    secrets_manager = boto3.client('secretsmanager')

    try:               
        response = secrets_manager.get_secret_value(SecretId=secret_name)  

    except ClientError as e:            
        error_code = e.response['Error']['Code']

        print(error_code)
        if error_code == 'ResourceNotFoundException':            
            raise Exception(f'ERROR: name not found') 
        else:           
            raise Exception(f'ERROR : {error_code}')
    else:
        secrets = json.loads(response['SecretString'])
        
        details = {
        'user': secrets['user'][0],
        'password': secrets['password'][0],
        'database': secrets['database'][0],
        'host':secrets['host'][0],
        'port':secrets['port']
        }
        
        return details['user'], details['password'], details['database'], details['host'], details['port'],


def make_connection(dotenv_path_string): 
    dotenv_path = Path(dotenv_path_string)

    load_dotenv(dotenv_path=dotenv_path)

   

    if dotenv_path_string.endswith('development'):
        user, password, database, host, port = pull_secrets()  
        conn = pg8000.connect(
        database=database,
        user=user,
        password=password,
        host=host,
        port=port        
        )        
    elif dotenv_path_string.endswith('test'):
        
        conn = pg8000.connect(
            database=os.getenv('database'),
            user=os.getenv('user'),
            password=os.getenv('password')
        )
    
    return conn
    

def get_titles(dbcur):
    sql = """SELECT table_name
    FROM information_schema.tables
    WHERE table_schema='public'
    AND table_type= 'BASE TABLE';"""
    try:
        dbcur.execute(sql)
        return dbcur.fetchall()
    except Exception as e:
        raise Exception(f"ERROR FETCHING TITLES: {e}")
      


def get_whole_table(dbcur, title):
    sql = f'SELECT * FROM {title[0]}'  
    try:  
        dbcur.execute(sql)
        rows = dbcur.fetchall()     
        keys = [k[0] for k in dbcur.description]   
        return rows, keys
    except Exception as e:
        raise Exception(f"ERROR FETCHING TABLE {title[0]}: {e}")
    
def get_recents_table(dbcur, title, created, updated):
    sql = f"SELECT * FROM {title[0]} WHERE (created_at > '{created}'::timestamp) OR (last_updated > '{updated}'::timestamp)"         
    try:  
        dbcur.execute(sql)
        rows = dbcur.fetchall()     
        keys = [k[0] for k in dbcur.description]   
        return rows, keys    
    except Exception as e:
        raise Exception(f"ERROR FETCHING TABLE {title[0]}: {e}")

def get_file_info_in_bucket(bucketname):
    try:
        s3 = boto3.client('s3') 
        return s3.list_objects_v2(Bucket=bucketname)
    except Exception as e:
        raise Exception(f"ERROR CHECKING OBJECTS IN BUCKET: {e}")

def get_bucket_name(bucket_prefix):
    
    s3 = boto3.client('s3')
    try:
        response = s3.list_buckets()
    except Exception as e:
        raise Exception(f"ERROR FETCHING BUCKET NAME: {e}")

    for bucket in response['Buckets']:
        if bucket['Name'].startswith(bucket_prefix):
            return bucket['Name']


def check_table_in_bucket(title, response):              
        if response['KeyCount'] == 0: return False
        filename = f"{title[0]}.parquet"  
        filenames= [file['Key'] for file in response['Contents']]        
        return filename in filenames


def get_parquet(title, bucketname, response):   
    filename = f"{title}.parquet"  
    if response['KeyCount'] == 0: return False
    if filename in [file['Key'] for file in response['Contents']]:       
         
        buffer = BytesIO()
        client = boto3.resource('s3')
        object=client.Object(bucketname, filename)
        object.download_fileobj(buffer)
        df = pd.read_parquet(buffer)       
        
        return df


def get_most_recent_time(title, bucketname, response):
    #function to find most recent update and creation times for table rows to check which values need to be updated
    #https://www.striim.com/blog/change-data-capture-cdc-what-it-is-and-how-it-works/
    updates = []
    creations = []
 
    #table = pd.read_parquet(f"./database-access/data/parquet/{title[0]}.parquet", engine='pyarrow')
    table = get_parquet(title[0], bucketname, response)        

    #compile a sorted list of 'last_updated' values and another sorted list of 'created_at' values existing inside previous readings
    for date in set(table['last_updated']):bisect.insort(updates, date)
    for date in set(table['created_at']):bisect.insort(creations, date)    

    #stores the most recent values from our previous readings
    last_update = updates[len(updates)-1]             
    last_creation = creations[len(creations)-1]

    #returns most recent values in dict
    return {        
        'created_at': last_creation,
        'last_updated': last_update
    }



def check_each_table(tables, dbcur, bucketname):     
    print("\n")
    to_be_added= []    
    response = get_file_info_in_bucket(bucketname)    

    for title in tables:                      
               
        
        #if there are no existing parquet files storing our data, create them
        if not check_table_in_bucket(title, response): 
            print(title[0], "to be added")         
            rows, keys = get_whole_table(dbcur, title)  
            to_be_added.append({title[0]: pd.DataFrame(rows, columns=keys)})
        else:
            #extract the most recent readings
            most_recent_readings = get_most_recent_time(title, bucketname, response)
             
            #extract raw data
            rows, keys  = get_recents_table(dbcur, title, most_recent_readings['created_at'], most_recent_readings['last_updated'])    
            results = [dict(zip(keys, row)) for row in rows]
        
            #if there any readings, add them to a dict with the table title as a key.             
            #append them into the to_be_added list
            #pd.DataFrame will transform the data into a pandas parquet format     
            
            if len(results) > 0:print(title[0], " is newer")
            else: print(title[0], "is not new")
            
            #if len(new_rows) > 0:print({title[0]: pd.DataFrame(new_rows)})
            if len(results) > 0:to_be_added.append({title[0]: pd.DataFrame(results)})
  
   
    return to_be_added


def push_to_cloud(object, bucketname): 
        #seperate key and value from object              
        key = [key for key in object.keys()][0]
        values = object[key] 

        #use key for file name, and value as the content for the file       
        values.to_parquet(f'/tmp/{key}.parquet') 

        #print(key)

        s3 = boto3.client('s3')        
        s3.upload_file(f'/tmp/{key}.parquet', bucketname, f'{key}.parquet')
        os.remove(f'/tmp/{key}.parquet')   
     
        return True


def  add_updates(updates, bucketname):
    #iterate through the list of dicts that need to be updated  
       
    for object in updates:                 
         push_to_cloud(object, bucketname)
 


def index(dotenv_path_string): 

    #function to connect to AWS RDS, find a list of table names, iterate through them and evaluate whether there any updates to make.
    #if not exit the programme.
    #if so, return a list of all neccessary updates in pandas parquet format  
     
     #connect to AWS RDS 
    conn = make_connection(dotenv_path_string)        
    dbcur = conn.cursor() 

    #get bucket name
    bucketname = get_bucket_name('scrumptious-squad-in-data-')   

    #execute SQL query for finding a list of table names inside RDS and store it inside tables variable
    tables = get_titles(dbcur)
    

    #iterate through the table_names and check for any values which need to updated, storing them in the 'updates' variable
    updates = check_each_table(tables, dbcur, bucketname)  
    dbcur.close()                
                                  
            
    add_updates(updates, bucketname)
    


#index('config/.env.development')


# Lambda handler
def someting(event, context):
    index('config/.env.development')
    logger.info("Completed")
    print("done")


