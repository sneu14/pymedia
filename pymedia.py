import paho.mqtt.client as mqtt
import time
import logging
import subprocess
import configparser
import socket
import os
import sys
import json
import threading
import validators

# Logging einrichten
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def popenAndCall(onExit, *popenArgs, **popenKWArgs):

    proc = subprocess.Popen(*popenArgs, **popenKWArgs)
    def runInThread(onExit, proc):
        proc.wait()
        onExit()
        return

    thread = threading.Thread(target=runInThread,
                            args=(onExit, proc))
    thread.start()

    return proc

class MQTTMediaPlayer:
    def __init__(self, broker_address="localhost", broker_port=1883):
        
        #MQTT Broker Verbindungsdetails
        self.mode = "video"
        self.monitor = 0
        self.volume = 100
        self.speed = 1
        self.broker_address = broker_address
        self.broker_port = broker_port
        self.playerstate_topic = self.mode + "/" + socket.gethostname() + "/state/player"
        self.instancestate_topic = self.mode + "/" + socket.gethostname() + "/state/instance"
        self.url_topics = [ self.mode + "/" + socket.gethostname() + "/url", self.mode + "/all/url" ]
        self.url_topics_loop = [ self.mode + "/" + socket.gethostname() + "/url_loop", self.mode + "/all/url_loop" ]
        self.control_topics = [ self.mode + "/" + socket.gethostname() + "/control", self.mode + "/all/control" ]
        self.seek_topics = [ self.mode + "/" + socket.gethostname() + "/seek", self.mode + "/all/seek" ]
        self.volume_topics = [ self.mode + "/" + socket.gethostname() + "/volume", self.mode + "/all/volume" ]
        self.speed_topics = [ self.mode + "/" + socket.gethostname() + "/speed", self.mode + "/all/speed" ]
        
        # MQTT Client mit aktueller API-Version initialisieren
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.will_set(self.instancestate_topic, payload="offline",qos=0, retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        
        # IPC-Socket für MPV
        self.ipc_socket = f"/tmp/mpv-socket-{os.getpid()}"
        
        # Audio-Player Status
        self.current_process = None
        self.is_playing = False
        self.is_paused = False
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
        
    def addURLTopic_Loop(self, t):
        self.url_topics_loop.append(t)
    
    def clearURLTopics_Loop(self):
        self.url_topics_loop = []
        
    def addControlTopic(self, t):
        self.control_topics.append(t)
    
    def clearControlTopics(self):
        self.control_topics = []

    def addSeekTopic(self, t):
        self.seek_topics.append(t)
        
    def clearSeekTopics(self):
        self.seek_topics = []
        
    def addVolumeTopic(self, t):
        self.volume_topics.append(t)

    def clearVolumeTopics(self):
        self.volume_topics = []
        
    def addSpeedTopic(self, t):
        self.speed_topics.append(t)

    def clearSpeedTopics(self):
        self.speed_topics = []
        
    def setPlayerStateTopic(self, t):
        self.playerstate_topic = t
        logger.info("Topic für Playerstatus: " + t)
 
    def setInstanceStateTopic(self, t):
        self.instancestate_topic = t
        logger.info("Topic für Instanzstatus: " + t)
        self.client.will_set(self.instancestate_topic, payload="offline",qos=0, retain=True)
 
    
    def connect(self):
        """Verbindung zum MQTT Broker herstellen"""
        try:
            self.client.connect(self.broker_address, self.broker_port, 60)
            self.client.publish(self.instancestate_topic,"online",0,True)
            self.client.loop_start()
            logger.info(f"Verbindung zum MQTT Broker {self.broker_address}:{self.broker_port} hergestellt")
            return True
        except Exception as e:
            logger.error(f"Fehler beim Verbinden zum MQTT Broker: {e}")
            return False
            
    def on_connect(self, client, userdata, flags, rc, properties=None):
        """Callback-Funktion bei erfolgreicher Verbindung"""
        logger.info(f"Verbunden mit Ergebniscode {rc}")
        
        logger.info("Abonniere URL-Topics")
        for x in self.url_topics:
            client.subscribe(x)
            logger.info("   " + x)
            
        logger.info("Abonniere URL-Topics_Loop")
        for x in self.url_topics_loop:
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

        logger.info("Abonniere Volume-Topics")
        for x in self.volume_topics:
            client.subscribe(x)
            logger.info("   " + x)
            
        logger.info("Abonniere Speed-Topics")
        for x in self.speed_topics:
            client.subscribe(x)
            logger.info("   " + x)


    def on_message(self, client, userdata, msg, properties=None):
        """Callback-Funktion bei eingehenden MQTT-Nachrichten"""
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        logger.info(f"Nachricht empfangen auf {topic}: {payload}")
        
        #if topic == self.url_topic1 or topic == self.url_topic2:
        if topic in self.url_topics:
            self.play_url(payload,False)
        if topic in self.url_topics_loop:
            self.play_url(payload, True)
        if topic in self.control_topics:
            self.control_playback(payload)
        if topic in self.seek_topics:
            self.control_seek(payload)
        if topic in self.volume_topics:
            self.control_volume(payload)
        if topic in self.speed_topics:
            self.control_speed(payload)
    
    def onPlayerExit(self):
        self.is_paused = False
        self.is_playing = False
        self.client.publish(self.playerstate_topic, "stop")
    
    def play_url(self, url, loop):
        if ( not validators.url(url) ):
            logger.warning("Invalid URL: " + (url))
            return
        """Audio-URL mit mpv abspielen"""
        try:
            # Beende jede laufende Wiedergabe
            if self.current_process:
                self.stop_playback()
            
            # Starte die neue Wiedergabe mit mpv (auch als Stream)
            self.current_url = url
            logger.info("Mode: " + self.mode)
            cmd = ""
            if self.mode == "video":
                cmd = ["mpv", "--no-terminal",
                       "--fs",
                       f"--screen={self.monitor}",
                       "--no-osc",
                       "--no-input-cursor"]

            else:
                cmd = ["mpv",
                       "--no-terminal",
                       "--no-video"]
            if (loop):
                cmd.append("--loop")
            cmd.append(f"--volume={self.volume}")
            cmd.append(f"--speed={self.speed}")
            cmd.append(f"--input-ipc-server={self.ipc_socket}")
            cmd.append(url)

            logger.info(f"Starte Wiedergabe von: {url}     {cmd}")
            #logger.info(cmd)
            self.current_process = popenAndCall(self.onPlayerExit,
                cmd, 
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            self.is_playing = True
            self.client.publish(self.playerstate_topic, "play")
            
            
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
                self.is_paused = True
                self.client.publish(self.playerstate_topic, "pause")
                logger.info("Wiedergabe pausiert")
        elif command == "play":
            if not self.is_playing:
                self._send_mpv_command({"command": ["set_property", "pause", False]})
                self.is_playing = True
                self.is_paused = False
                self.client.publish(self.playerstate_topic, "play")
                logger.info("Wiedergabe fortgesetzt")
        elif command == "stop":
            self.stop_playback()
        else:
            logger.warning(f"Unbekanntes Kommando: {command}")
            
    def control_seek(self, seconds):
        mode = True
        if ( seconds.startswith("+") or seconds.startswith("-")):
            mode = False
        try:
            t = float(seconds)
            if (mode):
                self._send_mpv_command({"command": ["seek", t, "absolute"]})
            else:
                self._send_mpv_command({"command": ["seek", t, "relative"]})
        except:
            logger.warning("Zeitstempel für Seek ungültig: " + seconds + " Fließkommazahl erwartet")

    def control_volume(self, volume):
        """Laustärke setzen"""
        try:
            t = float(volume)
            if self.is_playing or self.is_paused:
                self._send_mpv_command({"command": ["set_property", "volume", volume]})
            self.volume = volume
        except:
            logger.warning("Wert für Volume ungültig: " + volume + " Fließkommazahl erwartet")
            
    def control_speed(self, speed):
        """Geschwindigkeit setzen"""
        try:
            t = float(speed)
            if self.is_playing or self.is_paused:
                self._send_mpv_command({"command": ["set_property", "speed", speed]})
            self.volume = speed
        except:
            logger.warning("Wert für Geschwindigkeit ungültig: " + speed + " Fließkommazahl erwartet")

            
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
    return value.replace("___HOSTNAME___",socket.gethostname()).replace("___MONITOR___",str(mvalue))

if __name__ == "__main__":
    try:
        configFile = "config.ini"
        if len(sys.argv) >= 2:
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
        
        if config.has_option('General','Volume'):
            player.control_volume(config['General']['Volume'])

        
        try:
            player.mqtt_user_pw_set(config['Connection']['Username'], config['Connection']['Password'])
        except:
            logger.info("Keine Zugangsdaten für MQTT-Broker gesetzt")

        monitor = 0
        try:
            monitor = config['General']['Monitor']
            player.setMonitor(monitor)
        except:
            logger.info("Verwende Monitor: " + str(monitor))     
            
        t = 0
        try:
            t = replaceVars(config['Instance-Topics']['InstanceState'], monitor)
            player.setInstanceStateTopic(str(t))
        except:
            logger.info("Topic für Instanz Status: " + str(t))
        
        t = ""
        try:
            t = replaceVars(config['Instance-Topics']['PlayerState'], monitor)
            player.setPlayerStateTopic(t)
        except:
            logger.info("Topic für Player Status: " + t)  

        section = "URL-Topics"
        if config.has_section(section):
            player.clearURLTopics()    
            for x in dict(config.items(section)):
                player.addURLTopic(replaceVars(config[section][x], monitor))
                
        section = "URL-Topics_Loop"
        if config.has_section(section):
            player.clearURLTopics_Loop()    
            for x in dict(config.items(section)):
                player.addURLTopic_Loop(replaceVars(config[section][x], monitor))
        
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
        
        section = "Volume-Topics"
        if config.has_section(section):
            player.clearVolumeTopics()       
            for x in dict(config.items(section)):
                player.addVolumeTopic(replaceVars(config[section][x], monitor))
                
        section = "Speed-Topics"
        if config.has_section(section):
            player.clearSpeedTopics()       
            for x in dict(config.items(section)):
                player.addSpeedTopic(replaceVars(config[section][x], monitor))
        
        if ( not player.connect()):
            exit(1)
        
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
            

