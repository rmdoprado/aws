import boto3
import botocore

#initiating AWS boto3 reource and client
ec2 = boto3.resource('ec2')
client = boto3.client('ec2')
AccountId = boto3.client('sts').get_caller_identity().get('Account')

#initial variables
snapshot_days_keep = 5

#Argparse arguments
parser  = argparse.ArgumentParser(description='Print only instances to be terminated')
parser.add_argument('-p', '--printonly',action='store_true',help='Print only instances to be terminated')
arg = parser.parse_args()

#############################################################################################################
##########                                     Functions                                           ##########
#############################################################################################################


#########################                      Instances                   ##################################

def get_instances(*filter):
    print('Getting AWS instances based on the filters')
    set_filters =   {'Name': 'instance-state-name',
                    'Values': []
                    }
    for item in filter:
        set_filters['Values'].append(item)
        set_filters['Values'].append(item)
    instances_filtered = ec2.instances.filter(Filters=[set_filters])
    return instances_filtered


def terminate_instance (instance_id):
    try:
        ec2.instances.filter(InstanceIds=[instance_id]).terminate()
        print('Terminating instance {} started'.format(instance_id))
    except botocore.exceptions.WaiterError as e:
        print('Termination of the instance  {} failed - Error: {}'.format(instance_id,e))

def get_terminate_instance_progress (instance_id):
    try:
        print('Terminating instance {} in progress'.format(instance_id))
        instance = ec2.Instance(instance_id)
        instance.wait_until_terminated(
            Filters=[
                {
                    'Name': 'instance-id',
                    'Values': [instance_id,]
                },
            ]
        ) 
        print('Terminating instance {} completed'.format(instance.id))
    except botocore.exceptions.WaiterError as e:
       print('Termination of the instance  {} failed - Error: {}'.format(instance_id,e))



#########################                      Volumes                   ##################################

def get_volumes(instance):
    print('Getting volumes for the instance: {}'.format(instance.id))
    i = 0
    instance_volumes = {}
    for device in instance.block_device_mappings:
        volume_id = device['Ebs']['VolumeId']
        device_name = device['DeviceName']
        i += 1
        instance_volumes[i] = {}
        instance_volumes[i]['id'] = volume_id
        instance_volumes[i]['device_name'] = device_name

    return instance_volumes

def get_unattached_volume(devices):
    print('Getting volumes not deleted on the instance termination')
    VolumesToDelete = []
    for device in devices:
        volume_id = device['Ebs']['VolumeId']
        if device['Ebs']['DeleteOnTermination'] == False:
            VolumesToDelete.append(volume_id)
    return VolumesToDelete
            
        

def delete_unattached_volume(VolumesToDelete):
    try:
        for volume in VolumesToDelete:
            print('Deleting unattached volume {} in progress'.format(volume))
            response = client.delete_volume(
                VolumeId=volume
            )
            print('Deleting unattached volume {}, completed'.format(volume))  
    except:
        print('Deleting unattached volume {}, failed, please check it manually'.format(volume))
    return response

#########################                      Snapshots                   ##################################
def take_volumes_snapshot(instance):
    try:
        instance_volumes = get_volumes(instance)
        total_volumes = len(instance_volumes) + 1
        for x in range(1,total_volumes):
            volume_id = instance_volumes[x]['id']
            device_name = instance_volumes[x]['device_name']
            #print('Volume ID: {}, and Device name: {}'.format(volume_id,device_name))
            snapshot_id = take_snapshot(instance.id,volume_id, device_name)
            get_snapshot_progress(snapshot_id)
            create_snapshot = True

    except botocore.exceptions.WaiterError as e:
        print("Snapshot {} creating failed - Error: {}".format(snapshot_id,e))
        create_snapshot = False

    return create_snapshot


def take_snapshot(instance_id,volume_id, device_name):
    print('Creating snapshot for instance: {}, volume: {}'.format(instance_id,volume_id))
    #print(list_of_tags.keys)
    if 'name' in list_of_tags.keys():
        InstanceName = list_of_tags.get('name')
    else:
        InstanceName = 'None'
    snapshot = client.create_snapshot(
        Description='Snapshot from terminated instance {}, Volume ID: {}, DeviceName = {}'.format(instance.id, volume_id, device_name ),
        VolumeId=volume_id,
        TagSpecifications=[
            {
                'ResourceType':'snapshot',
                'Tags':[
                    {
                        'Key': 'Instance',
                        'Value': instance_id
                    },
                    {
                        'Key': 'Name',
                        'Value': InstanceName
                    },                    
                    {
                        'Key': 'VolumeID',
                        'Value': volume_id
                    },
                    {
                        'Key': 'DeviceName',
                        'Value': device_name
                    },
                    {
                        'Key': 'CreatedBy',
                        'Value': 'Termination-Automated'
                    },                                                          
                ]            
            },
        ],
    )

    snapshot_id = snapshot['SnapshotId']    
    return snapshot_id


def get_snapshot_progress (snapshot_id):
    snapshot = ec2.Snapshot(snapshot_id)
    print('Snapshot: {} in progress'.format(snapshot_id))
    snapshot.wait_until_completed(
        Filters=[
            {
                'Name': 'snapshot-id',
                'Values': [snapshot_id, ]
            }
        ]
    )
    print("Snapshot {} completed sucessful".format(snapshot_id))


#########################                      Main function                   ##################################

def process_termination (instance,message):
    print('Instance {} will be terminated because {}'.format(instance.id,message))
    
    if arg.printonly == False:
        print('Initiating the termination process for the instance: {}'.format(instance.id))
        # Task 1 - Get the Instances Volumes and take a snapshot of each.
        create_snapshot = take_volumes_snapshot(instance)
        if create_snapshot == True:
            try:
        # Task 2 - Terminate the instance.        
                terminate_instance(instance.id)
                get_terminate_instance_progress (instance.id)
        # Task 3 - Delete unattached volumes            
                volumes_to_delete = get_unattached_volume(instance.block_device_mappings)
                if volumes_to_delete:
                    delete_unattached_volume(volumes_to_delete)

            except botocore.exceptions.WaiterError as e:
                print("Terminating instance {} failed - Error: {}".format(instance.id,e))
    else:
        print('The argmumet --printonly was used and the instance: {} will not be terminated'.format(instance.id))

#############################################################################################################
##########                        End of the functions                                             ##########
#############################################################################################################


#########################                      Instances                   ##################################

#Getting instaces using a filter
instances = get_instances ('running','stopped')

#Loop all instancies running or stopped
for instance in instances:
    
    global list_of_tags
    list_of_tags = {}

    #Check if the Instance has Tags otherwise will terminate it
    if instance.tags:
        #Loop all instance tags and check if there is a particular Tag 'cost-center' and 'terminate
        for tag in instance.tags:
            list_of_tags[tag['Key'].lower()] = tag['Value'].lower()
        
        #It will proceed only if the instance does not have a AutoScaling/CloudDormation/Elastic Beanstalk Tag
        if 'aws:ec2launchtemplate:id' not in list_of_tags.keys() and 'aws:cloudformation:stack-id' not in list_of_tags.keys():
            #Terminate the instace if cannot find the tag cost-center of if the tag is empty
            if 'cost-center' not in list_of_tags.keys():
                process_termination(instance,'it is missing tag cost-center')

            if list_of_tags.get('cost-center') == '':
                process_termination(instance,'the tag cost-center is empty')

    else:
        #if the instance does not have any tag, it will be terminated
        process_termination(instance,'it is missing tag cost-center')