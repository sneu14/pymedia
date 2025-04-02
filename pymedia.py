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
    def __init__(self, mode, broker_address="localhost", broker_port=1883, username="", password="", state_topic="video/state", url_topic1 = "", url_topic2 = "", control1_topic = "", control2_topic = "", seek1_topic = "", seek2_topic= ""):
        
        #MQTT Broker Verbindungsdetails
        self.mode = mode
        self.broker_address = broker_address
        self.broker_port = broker_port
        self.state_topic = state_topic
        self.url_topic1 = url_topic1
        self.url_topic2 = url_topic2
        self.control1_topic = control1_topic
        self.control2_topic = control2_topic
        self.seek1_topic = seek1_topic
        self.seek2_topic = seek2_topic
        self.username = username
        self.password = password
        
        # MQTT Client mit aktueller API-Version initialisieren
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.username_pw_set(self.username, self.password)
        self.client.will_set(self.state_topic, payload="offline",qos=0, retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        
        # IPC-Socket für MPV
        self.ipc_socket = f"/tmp/mpv-socket-{os.getpid()}"
        
        # Audio-Player Status
        self.current_process = None
        self.is_playing = False
        self.current_url = None
 
        
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
        # Topics abonnieren
        client.subscribe(self.url_topic1)
        logger.info("Abonniert für: " + self.url_topic1)
        client.subscribe(self.url_topic2)
        logger.info("Abonniert für: " + self.url_topic2)
        client.subscribe(self.control1_topic)
        logger.info("Abonniert für: " + self.control1_topic)
        client.subscribe(self.control2_topic)
        logger.info("Abonniert für: " + self.control2_topic)
        client.subscribe(self.seek1_topic)
        logger.info("Abonniert für: " + self.seek1_topic)
        client.subscribe(self.seek2_topic)
        logger.info("Abonniert für: " + self.seek2_topic)
        
    def on_message(self, client, userdata, msg, properties=None):
        """Callback-Funktion bei eingehenden MQTT-Nachrichten"""
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        logger.info(f"Nachricht empfangen auf {topic}: {payload}")
        
        if topic == self.url_topic1 or topic == self.url_topic2:
            self.play_url(payload)
        if topic == self.control1_topic or topic == self.control2_topic:
            self.control_playback(payload)
        if topic == self.seek1_topic or topic == self.seek2_topic:
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
            if self.mode == "Video":
                cmd = ["mpv", "--no-terminal",
                       "--fs",
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

if __name__ == "__main__":
    try:
        configFile = sys.argv[1]
        #configFile = "config_video.ini"
        config = configparser.ConfigParser()
        config.read(configFile)
        # MQTT Broker-Einstellungen (ändern nach Bedarf)
        BROKER_ADDRESS = config['Connection']['Broker']  # Lokaler Broker
        BROKER_PORT = int(config['Connection']['Port'])            # Standardport
        TOPIC2 = config['Topics']['URL-Topic1'].replace("___HOSTNAME___",socket.gethostname())
        TOPIC1 = config['Topics']['URL-Topic2'].replace("___HOSTNAME___",socket.gethostname())
        STATE_TOPIC = config['Topics']['State'].replace("___HOSTNAME___",socket.gethostname())
        CONTROL1_TOPIC = config['Topics']['Control1'].replace("___HOSTNAME___",socket.gethostname())
        CONTROL2_TOPIC = config['Topics']['Control2'].replace("___HOSTNAME___",socket.gethostname())
        SEEK1_TOPIC = config['Topics']['Seek1'].replace("___HOSTNAME___",socket.gethostname())
        SEEK2_TOPIC = config['Topics']['Seek2'].replace("___HOSTNAME___",socket.gethostname())
        USERNAME = config['Connection']['Username']
        PASSWORD = config['Connection']['Password']
        MODE = config['General']['Mode']   
        
        # Audio Player starten
        player = MQTTMediaPlayer(MODE, BROKER_ADDRESS, BROKER_PORT, USERNAME, PASSWORD, STATE_TOPIC, TOPIC1, TOPIC2, CONTROL1_TOPIC, CONTROL2_TOPIC, SEEK1_TOPIC, SEEK2_TOPIC)
        player.connect()
        
        # Endlosschleife um das Programm am Laufen zu halten
        logger.info("Audio Player gestartet und wartet auf MQTT-Nachrichten...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Programm durch Benutzer beendet")
    
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {e}")
    finally:
        # Aufräumen
        if 'player' in locals():
            player.disconnect()
