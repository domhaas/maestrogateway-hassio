#!/usr/bin/python3
# coding: utf-8

import time
import sys
import os
import json
import logging
import coloredlogs
import threading
import paho.mqtt.client as mqtt
import websocket
from messages import MaestroMessageType, process_infostring, get_maestro_info, get_maestro_infoname, MAESTRO_INFORMATION, MaestroInformation
from commands import MaestroCommand, get_maestro_command, maestrocommandvalue_to_websocket_string, MaestroCommandValue, MAESTRO_COMMANDS

try:
    import thread
except ImportError:
    import _thread as thread

try:
    import queue
except ImportError:
    import Queue as queue

class SetQueue(queue.Queue):
    """ De-Duplicate message queue to prevent flipping values (Debounce) """
    def _init(self, maxsize):
        queue.Queue._init(self, maxsize)
        self.all_items = set()

    def _put(self, item):
        found = False
        for val in self.all_items:
            if val.command.name == item.command.name:
                found = True
                val.value = item.value
        if not found:
            queue.Queue._put(self, item)
            self.all_items.add(item)

    def _get(self):
        item = queue.Queue._get(self)
        self.all_items.remove(item)
        return item

get_stove_info_interval = 15.0
websocket_connected = False
socket_reconnect_count = 0
client = None
old_connection_status = None

# Logging
logger = logging.getLogger(__name__)
coloredlogs.install(level=os.getenv('LOG_LEVEL'), logger=logger)
CommandQueue = SetQueue()
MaestroInfoMessageCache = {}

def on_connect_mqtt(client, userdata, flags, rc):
    logger.info("MQTT: Connected to broker. " + str(rc))
    if _MQTT_PAYLOAD_TYPE == 'TOPIC':
        logger.info('MQTT: Subscribed to topic "' + str(_MQTT_TOPIC_SUB) + '#"')
        client.subscribe(_MQTT_TOPIC_SUB+'#', qos=1)
        publish_availabletopics()
    else:
        logger.info('MQTT: Subscribed to topic "' + str(_MQTT_TOPIC_SUB) + '"')
        client.subscribe(_MQTT_TOPIC_SUB, qos=1)

def on_disconnect_mqtt(client, userdata, rc):
    if rc != 0:
        logger.info("MQTT: Unexpected disconnection -> try to reconnect...")

def on_message_mqtt(client, userdata, message):
    try:
        maestrocommand = None
        cmd_value = None
        payload = str(message.payload.decode())
        if _MQTT_PAYLOAD_TYPE == 'TOPIC':
            topic = str(message.topic)
            command = topic[str(topic).rindex('/')+1:]
            logger.debug(f"Command topic received: {topic}")
            maestrocommand = get_maestro_command(command)
            cmd_value = payload
        else:
            logger.debug(f"MQTT: Message received: {payload}")
            res = json.loads(payload)
            maestrocommand = get_maestro_command(res["Command"])
            cmd_value = res["Value"]
        if maestrocommand.name == "Unknown":
            logger.debug(f"Unknown Maestro Command Received. Ignoring. {payload}")
        elif maestrocommand.name == "Refresh":
            logger.debug('Clearing the message cache')
            MaestroInfoMessageCache.clear()
        else:
            logger.debug('Queueing Command ' + maestrocommand.name + ' ' + str(payload))
            CommandQueue.put(MaestroCommandValue(maestrocommand, cmd_value))
    except Exception as e:
            logger.error('Exception in on_message_mqtt: '+ str(e))

def recuperoinfo_enqueue():
    """Get Stove information every x seconds as long as there is a websocket connection"""
    threading.Timer(get_stove_info_interval, recuperoinfo_enqueue).start()
    if websocket_connected:
        CommandQueue.put(MaestroCommandValue(MaestroCommand('GetInfo', 0, 'GetInfo', 'GetInfo'), 0))
        client.publish(_MQTT_TOPIC_PUB + 'state',  'ON',  1)    

def send_connection_status_message(message):
    global old_connection_status
    if old_connection_status != message:
        if _MQTT_PAYLOAD_TYPE == 'TOPIC':
            json_dictionary = json.loads(str(json.dumps(message)))
            for key in json_dictionary:
                logger.info('MQTT: publish to Topic "' + str(_MQTT_TOPIC_PUB + key) +
                        '", Message : ' + str(json_dictionary[key]))
                client.publish(_MQTT_TOPIC_PUB+key, json_dictionary[key], 1)
        else:
            client.publish(_MQTT_TOPIC_PUB, json.dumps(message), 1)
        old_connection_status = message

def process_info_message(message):
    """Process websocket array string that has the stove Info message"""
    res = process_infostring(message)
    maestro_info_message_publish = {}
        
    for item in res:
        if item not in MaestroInfoMessageCache:
            MaestroInfoMessageCache[item] = res[item]
            maestro_info_message_publish[item] = res[item]
        elif MaestroInfoMessageCache[item] != res[item]:
            MaestroInfoMessageCache[item] = res[item]
            maestro_info_message_publish[item] = res[item]

    if len(maestro_info_message_publish) > 0:
        if _MQTT_PAYLOAD_TYPE == 'TOPIC':
            logger.info(str(json.dumps(maestro_info_message_publish)))
            for key in maestro_info_message_publish:
                logger.info('MQTT: publish to Topic "' + str(_MQTT_TOPIC_PUB + key) +'", Message : ' + str(maestro_info_message_publish[key]))
                client.publish(_MQTT_TOPIC_PUB + key, maestro_info_message_publish[key], 1)
        else:
            client.publish(_MQTT_TOPIC_PUB, json.dumps(maestro_info_message_publish), 1)


def on_message(ws, message):
    message_array = message.split("|")
    if message_array[0] == MaestroMessageType.Info.value:
        process_info_message(message)
    elif message_array[0] == MaestroMessageType.StringData.value:
        logger.info('Date Time Set ' + str(message_array[1]))
    else:
        logger.error('Unsupported message type received!')

def on_error(ws, error):
    logger.error(error)

def on_close(ws, close_status_code, close_msg):
    logger.info('Websocket: Disconnected')
    global websocket_connected
    websocket_connected = False

def on_open(ws):
    logger.info('Websocket: Connected')
    send_connection_status_message({"Status":"connected"})
    global websocket_connected
    websocket_connected = True
    socket_reconnect_count = 0
    def run(*args):
        for i in range(360*4):
            time.sleep(0.25)
            while not CommandQueue.empty():
                command = CommandQueue.get()
                cmd = maestrocommandvalue_to_websocket_string(command)
                if cmd != "":
                    logger.info("Websocket: Send " + str(cmd))
                    ws.send(cmd)
                else:
                    logger.error(f"Invalid command: {command.name} Value: {command.value}")
        logger.info('Closing Websocket Connection')
        ws.close()
    thread.start_new_thread(run, ())

def start_mqtt():
    global client
    logger.info('Connection in progress to the MQTT broker (IP:' +
                _MQTT_ip + ' PORT:'+str(_MQTT_port)+')')
    client = mqtt.Client(client_id="MCZ_PelletStove")
    if _MQTT_authentication:
        logger.info('mqtt authentication enabled')
        client.username_pw_set(username=_MQTT_user, password=_MQTT_pass)
    client.on_connect = on_connect_mqtt
    client.on_disconnect = on_disconnect_mqtt
    client.on_message = on_message_mqtt
    client.connect(_MQTT_ip, _MQTT_port)
    client.loop_start()

def publish_availabletopics():  
    logger.info(_MQTT_TOPIC_PUB + 'state')  
    # Publish topics that have stat and command
    for item in MAESTRO_INFORMATION:
        logger.info(_MQTT_TOPIC_PUB + item.name)        
        maestrocommand = get_maestro_command(item.name)        
        if maestrocommand.name != "Unknown":
            logger.info(_MQTT_TOPIC_SUB + item.name)  

    # publish topics that have command only
    for item in MAESTRO_COMMANDS:
        homeassistanttype = 'sensor'   
        maestroinfo = get_maestro_infoname(item.name)
        if maestroinfo.name == "Unknown":
            logger.info(_MQTT_TOPIC_SUB + item.name) 

def init_config():
    print('Reading config from envionment variables')
    global _MQTT_ip
    _MQTT_ip = os.getenv('MQTT_ip')

    global _MQTT_port
    _MQTT_port = int(os.getenv('MQTT_port'))

    global _MQTT_authentication
    _MQTT_authentication = os.getenv('MQTT_authentication') == "True"

    global _MQTT_user
    _MQTT_user = os.getenv('MQTT_user')

    global _MQTT_pass
    _MQTT_pass = os.getenv('MQTT_pass')

    global _MQTT_TOPIC_PUB
    _MQTT_TOPIC_PUB = os.getenv('MQTT_TOPIC_PUB')

    global _MQTT_TOPIC_SUB
    _MQTT_TOPIC_SUB = os.getenv('MQTT_TOPIC_SUB')

    global _MQTT_PAYLOAD_TYPE
    _MQTT_PAYLOAD_TYPE = os.getenv('MQTT_PAYLOAD_TYPE')

    global _WS_RECONNECTS_BEFORE_ALERT
    _WS_RECONNECTS_BEFORE_ALERT = int(os.getenv('WS_RECONNECTS_BEFORE_ALERT'))

    global _MCZip
    _MCZip = os.getenv('MCZip')
    
    global _MCZport
    _MCZport = os.getenv('MCZport')
        
    
if __name__ == "__main__":
    init_config()        
    recuperoinfo_enqueue()
    socket_reconnect_count = 0
    start_mqtt()

    while True:
        logger.info("Websocket: Establishing connection to server (IP:"+_MCZip+" PORT:"+_MCZport+")")
        ws = websocket.WebSocketApp("ws://" + _MCZip + ":" + _MCZport,
                                    on_message=on_message,
                                    on_error=on_error,
                                    on_close=on_close)
        ws.on_open = on_open

        ws.run_forever(ping_interval=5, ping_timeout=2, suppress_origin=True)
        time.sleep(1)
        socket_reconnect_count = socket_reconnect_count + 1
        logger.info("Socket Reconnection Count: " + str(socket_reconnect_count))
        if socket_reconnect_count>_WS_RECONNECTS_BEFORE_ALERT:
            send_connection_status_message({"Status":"disconnected"})
            socket_reconnect_count = 0
