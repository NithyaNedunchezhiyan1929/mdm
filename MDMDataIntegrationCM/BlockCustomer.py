import json
import boto3
import logging
import os 

# Set up Logging feature for CloudWatch Logs
Lambda_logger = logging.getLogger()
Lambda_logger.setLevel(logging.INFO)

# Set up Boto3 clients
lambda_client = boto3.client('lambda')
sqs = boto3.client('sqs')

# Read Environment Variables for ARN
MDM_WF_SNS = os.environ['PUBLISH_WF_SNS']
MDM_ES_SNS = os.environ['PUBLISH_ES_SNS']
MDM_FIELD_MAPPING = os.environ['FN_FIELD_MAP']
PIPO_MDM_BLOCKCUST = os.environ['PIPO_BLOCKCUST']
MDM_BLOCK_REC = os.envron['FN_BLOCK_MDM_REC']

# Read Environment Variables for variables
PIPO_USER = os.environ['PIPO_USER']
PIPO_PWD = os.environ['PIPO_PASS']
PIPO_AUTH = os.environ['PIPO_AUTH']

# Flags for JSONFieldMapping module (constants)
erp = 1
business = 2
mdmdw = 3

# Template for WF upstream data 
wfData = {
    "WorkflowId": "",
    "SystemName": "",
    "Role": "",
    "SalesOrg": "",
    "OperationName": "",
    "MdmNumber": "",
    "CustomerNumber": "",
    "isBlocked": ""
}

def lambda_handler(event, context):

    Lambda_logger.info('Starting Block Customer Process')    
    if event.get("source") in ["aws.events", "serverless-plugin-warmup"]:
        print('Lambda is warm!')

    # This methods retuns the json keys mapped with respective ERP system
    print ('Incoming Data : \n', event)
    message = event['Message']
    esData = event['Message']
    erpFields = MapJsonFields (message, erp)
    erpInput = json.loads(erpFields)
    print ('Sending Customer to block :: ', erpInput)

    # Call API GW to send Block Customer request through PIPO endpoint
    erpRes = BlockErpCustomer(erpInput) # Self function 
    erpData = json.loads(erpRes)
    print ("Response from ERP :: ", erpData, type(erpData))
    if erpData['STATUS_CODE'] == 200:
        print('Customer Blocked is :',erpData['CUSTOMER_NO'])
        # This method retuns the json keys mapped with RedShift schema
        edwRes = MapJsonFields (message, mdmdw)
        edwData = json.loads(edwRes)
        # Block MDM Record
		mdmblockresponse = BlockCMRecord(edwData)
		mdmupdatedata = json.loads(mdmblockresponse)
        print("RS Response ",mdmupdatedata)
        if mdmupdatedata['statusCode'] == 200:            
            # Publish SNS message to WF Engine
            wfData['WorkflowId'] = message['WorkflowId']
            wfData['SystemName'] = message['SystemName']
            wfData['Role'] = message['Role']
            wfData['SalesOrg'] = message['SalesOrg']
            wfData['OperationName'] = message['OperationName']
            wfData['MdmNumber'] = edwData["mdm_customer_id"]
            wfData['CustomerNumber'] = edwData["customer_number"]
            wfData['isBlocked'] = "TRUE"
            print('WF Data ', wfData)
            wfResponse = publishWF(json.dumps(wfData))
            print(wfResponse)
            
            # Publish SNS message to Elastic Search
            if event['Message']['Flag'] >0: 
                del event['Message']['Flag']
        

            esMessage = event['Message']
            esMessage['Data']['MdmNumber'] = edwData["mdm_customer_id"]
            print('Message \n', esMessage)
            print('ES Data ', esMessage)
            esResponse = publishES(json.dumps(esMessage))
            print (esResponse)
        else:
            print ('Failed to Block MDM Record')
            wfData['WorkflowId'] = message['WorkflowId']
            wfData['Role'] = message['Role']
            wfData['SalesOrg'] = message['SalesOrg']
            wfData['SystemName'] = message['SystemName']
            wfData['OperationName'] = message['OperationName']
            wfData['MdmNumber'] = 'null'
            wfData['CustomerNumber'] = edwData["customer_number"]
            wfData['isBlocked'] = "FALSE"
            wfResponse = publishWF(json.dumps(wfData))
    else:
        print ('Failed to Block ERP Record')
        wfData['WorkflowId'] = message['WorkflowId']
        wfData['Role'] = message['Role']
        wfData['SalesOrg'] = message['SalesOrg']
        wfData['SystemName'] = message['SystemName']
        wfData['OperationName'] = message['OperationName']
        wfData['MdmNumber'] = 'null'
        wfData['CustomerNumber'] = 'null'
        wfData['isBlocked'] = 'FALSE'
        print('WF Data ', wfData)
        wfResponse = publishWF(json.dumps(wfData))

def MapJsonFields(businessFields,convType):
    print ("Inside Mapping for Fields")
    businessFields["Flag"]=convType
    print ("Before Conversion :: ", businessFields)
    response = lambda_client.invoke(
        FunctionName=MDM_FIELD_MAPPING,
        InvocationType='RequestResponse',
        Payload=json.dumps(businessFields)
        )
    print ("MAP RESPONSE ::::: ", response)
    record = response['Payload'].read().decode('utf8').replace("'", '"')
    print ("After Conversion :: ", json.loads(record), type(record))
    return json.loads(record)

def BlockCMRecord(data):
    # This method will block customer in RedShift 
    # print ('Blocking MDM record...')
    response = lambda_client.invoke(
        FunctionName=MDM_BLOCK_REC,
        InvocationType='RequestResponse',
        Payload=json.dumps(data)
        )
    #record = response['statusCode'].read().decode('utf8').replace("'", '"')
    # print ('in MDM : ', record, type(record))
    # print ('Exiting Block MDM ')
    return json.loads(response)
    
def BlockErpCustomer(data):
    print ('Inside Block ERP ')
    print ("Block customer :: ", data, type(data))
    ##
    Lambda_logger.info('Starting Block Customer SAP')

    headers = {"Authorization":PIPO_AUTH}
    payload = json.dumps(data)
    print ('Sent Input ',payload, type(payload))
    response = requests.post(PIPO_MDM_BLOCKCUST,data=payload, timeout=10, auth=(PIPO_USER,PIPO_PWD), headers=headers)
    res = response.json()
    print ('Received Response',res['STATUS_CODE']) 
    Lambda_logger.info('Ending Block Customer SAP')
    return json.dumps(res)

    ##
    # print ("Response in ERP ", response)
    # record = response['Payload'].read().decode('utf8').replace("'", '"')
    # print ('in erp : ', record, type(record))
    # return json.loads(record)

def publishES(data):
    # This method will publish MDM record to Elastic Search SNS Topic
    response = lambda_client.invoke(
        FunctionName=MDM_ES_SNS,
        InvocationType='RequestResponse',
        Payload=json.dumps(data)
        )
    record = response['Payload'].read().decode('utf8').replace("'", '"')
    return json.loads(record)    
    

    
def publishWF(data):
    # This method will publish upstream response
    response = lambda_client.invoke(
        FunctionName=MDM_WF_SNS,
        InvocationType='RequestResponse',
        Payload=json.dumps(data)
        )
    record = response['Payload'].read().decode('utf8').replace("'", '"')
    return json.loads(record)
