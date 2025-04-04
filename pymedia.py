import paho.mqtt.client as mqtt
import time
import logging
import subprocess
import configparser
import socket
import os
import sys
import json

# Logging einrichten
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MQTTMediaPlayer:
    def __init__(self, broker_address="localhost", broker_port=1883):
        
        #MQTT Broker Verbindungsdetails
        self.mode = "video"
        self.monitor = 0
        self.broker_address = broker_address
        self.broker_port = broker_port
        self.state_topic = self.mode + "/" + socket.gethostname() + "/state"
        self.url_topics = [ self.mode + "/" + socket.gethostname() + "/url", self.mode + "/all/url" ]
        self.control_topics = [ self.mode + "/" + socket.gethostname() + "/control", self.mode + "/all/control" ]
        self.seek_topics = [ self.mode + "/" + socket.gethostname() + "/seek", self.mode + "/all/seek" ]
        
        # MQTT Client mit aktueller API-Version initialisieren
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.will_set(self.state_topic, payload="offline",qos=0, retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        
        # IPC-Socket für MPV
        self.ipc_socket = f"/tmp/mpv-socket-{os.getpid()}"
        
        # Audio-Player Status
        self.current_process = None
        self.is_playing = False
        self.current_url = None
        
        
    def setMode(self, mode):
        if mode == "audio" or mode == "video":
            self.mode = mode
        else:
            logger.warn("Ungültiger Betriebsmodus. Nur Audio oder Video möglich")
        
    def setMonitor(self, m):
        try:
            self.monitor = int(m)
        except:
            logger.warn("Ungültige Monitor ID: " + m)
            
    def mqtt_user_pw_set(self, u,p):
        self.client.username_pw_set(u,p)
        
    def addURLTopic(self, t):
        self.url_topics.append(t)
        
    def clearURLTopics(self):
        self.url_topics = []
        
    def addControlTopic(self, t):
        self.control_topics.append(t)
    
    def clearControlTopics(self):
        self.control_topics = []

    def addSeekTopic(self, t):
        self.seek_topics.append(t)
        
    def clearSeekTopics(self):
        self.seek_topics = []
    
    def connect(self):
        """Verbindung zum MQTT Broker herstellen"""
        try:
            self.client.connect(self.broker_address, self.broker_port, 60)
            self.client.publish(self.state_topic,"online",0,True)
            self.client.loop_start()
            logger.info(f"Verbindung zum MQTT Broker {self.broker_address}:{self.broker_port} hergestellt")
        except Exception as e:
            logger.error(f"Fehler beim Verbinden zum MQTT Broker: {e}")
            
    def on_connect(self, client, userdata, flags, rc, properties=None):
        """Callback-Funktion bei erfolgreicher Verbindung"""
        logger.info(f"Verbunden mit Ergebniscode {rc}")
        
        logger.info("Abonniere URL-Topics")
        for x in self.url_topics:
            client.subscribe(x)
            logger.info("   " + x)
            
        logger.info("Abonniere Control-Topics")
        for x in self.control_topics:
            client.subscribe(x)
            logger.info("   " + x)
        
        logger.info("Abonniere Seek-Topics")
        for x in self.seek_topics:
            client.subscribe(x)
            logger.info("   " + x)

    def on_message(self, client, userdata, msg, properties=None):
        """Callback-Funktion bei eingehenden MQTT-Nachrichten"""
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        logger.info(f"Nachricht empfangen auf {topic}: {payload}")
        
        #if topic == self.url_topic1 or topic == self.url_topic2:
        if topic in self.url_topics:
            self.play_url(payload)
        if topic in self.control_topics:
            self.control_playback(payload)
        if topic in self.seek_topics:
            self.control_seek(payload)
    
    def play_url(self, url):
        """Audio-URL mit mpv abspielen"""
        try:
            # Beende jede laufende Wiedergabe
            if self.current_process:
                self.stop_playback()
            
            # Starte die neue Wiedergabe mit mpv (auch als Stream)
            self.current_url = url
            logger.info("Mode: " + self.mode)
            if self.mode == "video":
                cmd = ["mpv", "--no-terminal",
                       "--fs",
                       f"--screen={self.monitor}",
                       "--no-osc",
                       "--no-input-cursor",
                       f"--input-ipc-server={self.ipc_socket}",
                       url]
                self.current_process = subprocess.Popen(
                    cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE
                )
            else:
                cmd = ["mpv",
                       "--no-terminal",
                       "--no-video",
                       f"--input-ipc-server={self.ipc_socket}",
                       url]
                self.current_process = subprocess.Popen(
                    cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE
                )
            self.is_playing = True
            self.client.publish(self.state_topic, "playing",0,True)
            logger.info(f"Starte Wiedergabe von: {url}")
            
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Fehler beim Abspielen der URL {url}: {e}")
    
    def control_playback(self, command):
        """Steuerung der Wiedergabe (pause/stop)"""
        if not self.current_process:
            logger.warning("Keine aktive Wiedergabe vorhanden")
            return
            
        if command == "pause":
            if self.is_playing:
                # Pause an mpv senden (SIGTSTP)
                self._send_mpv_command({"command": ["set_property", "pause", True]})
                self.is_playing = False
                self.client.publish(self.state_topic, "paused",0,True)
                logger.info("Wiedergabe pausiert")
        elif command == "play":
            if not self.is_playing:
                self._send_mpv_command({"command": ["set_property", "pause", False]})
                self.is_playing = True
                self.client.publish(self.state_topic, "playing",0,True)
                logger.info("Wiedergabe fortgesetzt")
        elif command == "stop":
            self.stop_playback()
            self.client.publish(self.state_topic, "stopped",0,True)
        else:
            logger.warning(f"Unbekanntes Kommando: {command}")
            
    def control_seek(self, seconds):
        """Zu Zeitstempel springen"""
        try:
            t = float(seconds)
            self._send_mpv_command({"command": ["seek", t, "absolute"]})
        except:
            logger.warning("Zeitstempel für Seek ungültig: " + seconds + " Fließkommazahl erwartet")

            
    def _send_mpv_command(self, command):
        """Sendet einen Befehl an den mpv-Player über den IPC-Socket"""
        if not os.path.exists(self.ipc_socket):
            logger.error(f"MPV IPC-Socket nicht gefunden: {self.ipc_socket}")
            return False
        
        try:
            # Mit dem Socket verbinden
            import socket
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.ipc_socket)
            
            # Befehl senden
            command_json = json.dumps(command) + "\n"
            sock.sendall(command_json.encode())
            sock.close()
            return True
        except Exception as e:
            logger.error(f"Fehler beim Senden des Befehls an MPV: {e}")
            return False
    
    def stop_playback(self):
        """Wiedergabe stoppen"""
        if self.current_process:
            self.current_process.terminate()
            try:
                self.current_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.current_process.kill()
            self.current_process = None
            self.is_playing = False
            logger.info("Wiedergabe gestoppt")
    
    def disconnect(self):
        """Verbindung zum MQTT Broker trennen"""
        self.stop_playback()
        #self.client.loop_stop()
        self.client.disconnect()
        logger.info("MQTT-Verbindung getrennt")

def replaceVars(value, mvalue):
    return value.replace("___HOSTNAME___",socket.gethostname()).replace("___MONITOR___",mvalue)

if __name__ == "__main__":
    try:
        configFile = "config.ini"
        if len(sys.argv) == 2:
            configFile = sys.argv[1]

        config = configparser.ConfigParser()
        logger.info("Verwende Configdatei: " + configFile)
        config.read(configFile)
            
        try:
            BROKER_ADDRESS = config['Connection']['Broker']
        except:
            BROKER_ADDRESS = "localhost"
        
        try:
            BROKER_PORT = int(config['Connection']['Port'])
        except:
            BROKER_PORT = 1883
            
 
        player = MQTTMediaPlayer(BROKER_ADDRESS, BROKER_PORT)
        try:
            player.setMode(config['General']['Mode'])
        except:
            logger.info("Starte im Modus: Video")
        
        try:
            player.mqtt_user_pw_set(config['Connection']['Username'], config['Connection']['Password'])
        except:
            logger.info("Keine Zugangsdaten für MQTT-Broker gesetzt")

        monitor = 0
        try:
            monitor = config['General']['Monitor']
            player.setMonitor(monitor)
        except:
            logger.info("Verwende Monitor 0")        

        section = "URL-Topics"
        if config.has_section(section):
            player.clearURLTopics()    
            for x in dict(config.items(section)):
                player.addURLTopic(replaceVars(config[section][x], monitor))
        
        section = "Control-Topics"
        if config.has_section(section):
            player.clearControlTopics()      
            for x in dict(config.items(section)):
                player.addControlTopic(replaceVars(config[section][x], monitor))
        
        section = "Seek-Topics"
        if config.has_section(section):
            player.clearSeekTopics()       
            for x in dict(config.items(section)):
                player.addSeekTopic(replaceVars(config[section][x], monitor))
        
        player.connect()
        
        # Endlosschleife um das Programm am Laufen zu halten
        logger.info("Player gestartet und wartet auf MQTT-Nachrichten...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Programm durch Benutzer beendet")
    
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {e.with_traceback()}")
    finally:
        # Aufräumen
        if 'player' in locals():
            player.disconnect()
            

