import os
import json
import urllib.request
import urllib.parse
import urllib.error
import websocket
import threading
import time
from colorama import init, Fore, Style
from ui.interface import display_ansi_art

init(autoreset=True)

active_voice_clients = {}

def load_tokens():
    with open('data/tokens.txt', 'r') as f:
        return [token.strip() for token in f.readlines() if token.strip()]

def get_centered_input(prompt_text):
    terminal_width = os.get_terminal_size().columns
    terminal_height = os.get_terminal_size().lines
    
    vertical_position = terminal_height // 5
    
    for _ in range(vertical_position):
        print()
    
    prompt_length = len(prompt_text.replace(Fore.BLUE, '').replace(Style.BRIGHT, '').replace(Style.RESET_ALL, ''))
    padding = (terminal_width - prompt_length) // 2
    centered_prompt = ' ' * padding + prompt_text
    
    return input(centered_prompt)

def parse_command(command):
    parts = command.split()
    
    if len(parts) < 3 or parts[0] != 'vc':
        return None
    
    subcommand = parts[1]
    valid_subcommands = ['connect', 'disconnect', 'stream', 'video', 'mute', 'unmute', 'deafen', 'undeafen', 'list', 'message']
    
    if subcommand not in valid_subcommands:
        return None
    
    if subcommand in ['connect', 'disconnect']:
        if len(parts) < 4 or parts[2] != 'tok':
            return None
        try:
            token_index = int(parts[3])
        except (IndexError, ValueError):
            return None
        
        channel_id = None
        if len(parts) >= 6 and parts[4] == '-cid':
            try:
                channel_id = int(parts[5])
            except ValueError:
                return None
        
        return {
            'subcommand': subcommand,
            'token_index': token_index,
            'channel_id': channel_id
        }
    
    elif subcommand in ['stream', 'video', 'mute', 'unmute', 'deafen', 'undeafen']:
        if len(parts) < 4 or parts[2] != 'tok':
            return None
        try:
            token_index = int(parts[3])
        except (IndexError, ValueError):
            return None
        
        return {
            'subcommand': subcommand,
            'token_index': token_index,
            'channel_id': None
        }
    
    elif subcommand == 'list':
        return {
            'subcommand': subcommand,
            'token_index': None,
            'channel_id': None
        }
    
    elif subcommand == 'message':
        if len(parts) < 6:
            return None
        
        if parts[2] != 'tok':
            return None
        
        try:
            token_index = int(parts[3])
        except (IndexError, ValueError):
            return None
        
        cid_index = -1
        for i, part in enumerate(parts):
            if part == '-cid':
                cid_index = i
                break
        
        if cid_index == -1 or cid_index + 1 >= len(parts):
            return None
        
        try:
            channel_id = int(parts[cid_index + 1])
        except ValueError:
            return None
        
        message_parts = parts[4:cid_index]
        if not message_parts:
            return None
        
        message = ' '.join(message_parts)
        
        return {
            'subcommand': subcommand,
            'token_index': token_index,
            'channel_id': channel_id,
            'message': message
        }
    
    return None

class DiscordVoiceClient:
    def __init__(self, token, token_index):
        self.token = token
        self.token_index = token_index
        self.session_id = None
        self.user_id = None
        self.username = None
        self.gateway_ws = None
        self.voice_ws = None
        self.connected = False
        self.voice_connected = False
        self.current_guild_id = None
        self.current_channel_id = None
        self.self_mute = False
        self.self_deaf = False
        self.self_stream = False
        self.self_video = False
        self.stream_key = None
        self.api_base = "https://discord.com/api/v9"
        self.heartbeat_thread = None
        self.keepalive_thread = None
        self.heartbeat_interval = None
        self.last_heartbeat_ack = True
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.last_keepalive = time.time()
        
    def make_request(self, method, endpoint, data=None):
        url = f"{self.api_base}{endpoint}"
        headers = {
            'Authorization': self.token,
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        if data:
            data = json.dumps(data).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        
        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 204:
                    return True
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            try:
                error_data = json.loads(e.read().decode('utf-8'))
                print(f"{Fore.RED}HTTP Error {e.code}: {error_data.get('message', 'Unknown error')}{Style.RESET_ALL}")
            except:
                print(f"{Fore.RED}HTTP Error {e.code}{Style.RESET_ALL}")
            return None
        except Exception as e:
            print(f"{Fore.RED}Request error: {str(e)}{Style.RESET_ALL}")
            return None
    
    def send_message(self, channel_id, message):
        message_data = {
            'content': message,
            'tts': False
        }
        
        response = self.make_request('POST', f'/channels/{channel_id}/messages', message_data)
        if response:
            return True, f"Message sent successfully"
        return False, "Failed to send message"
    
    def get_gateway_url(self):
        response = self.make_request('GET', '/gateway')
        if response:
            return response.get('url')
        return None
    
    def on_gateway_message(self, ws, message):
        try:
            data = json.loads(message)
            op = data.get('op')
            
            if op == 10:
                self.heartbeat_interval = data['d']['heartbeat_interval']
                self.start_heartbeat(ws, self.heartbeat_interval)
                self.start_keepalive()
                
                identify_payload = {
                    'op': 2,
                    'd': {
                        'token': self.token,
                        'properties': {
                            '$os': 'windows',
                            '$browser': 'Discord Client',
                            '$device': 'desktop'
                        }
                    }
                }
                ws.send(json.dumps(identify_payload))
                
            elif op == 11:
                self.last_heartbeat_ack = True
                
            elif op == 0:
                event_type = data.get('t')
                event_data = data.get('d')
                
                if event_type == 'READY':
                    self.session_id = event_data['session_id']
                    self.user_id = event_data['user']['id']
                    self.username = f"{event_data['user']['username']}#{event_data['user'].get('discriminator', '0')}"
                    self.reconnect_attempts = 0
                    
                elif event_type == 'VOICE_STATE_UPDATE':
                    if event_data['user_id'] == self.user_id:
                        if event_data.get('channel_id'):
                            self.voice_connected = True
                            self.current_channel_id = event_data['channel_id']
                        else:
                            self.voice_connected = False
                            self.current_channel_id = None
                        
                        self.self_mute = event_data.get('self_mute', False)
                        self.self_deaf = event_data.get('self_deaf', False)
                        self.self_stream = event_data.get('self_stream', False)
                        self.self_video = event_data.get('self_video', False)
                        
                elif event_type == 'STREAM_CREATE':
                    if event_data.get('user_id') == self.user_id:
                        self.stream_key = event_data.get('stream_key')
                        self.self_stream = True
                        
                elif event_type == 'STREAM_DELETE':
                    if event_data.get('stream_key') == self.stream_key:
                        self.stream_key = None
                        self.self_stream = False
                        
                elif event_type == 'VOICE_SERVER_UPDATE':
                    pass
        except Exception as e:
            pass
    
    def on_gateway_error(self, ws, error):
        if self.connected:
            self.attempt_reconnect()
    
    def on_gateway_close(self, ws, close_status_code, close_msg):
        if self.connected and self.reconnect_attempts < self.max_reconnect_attempts:
            self.attempt_reconnect()
    
    def start_heartbeat(self, ws, interval):
        def heartbeat():
            while self.connected:
                try:
                    if not self.last_heartbeat_ack:
                        self.attempt_reconnect()
                        break
                    
                    self.last_heartbeat_ack = False
                    ws.send(json.dumps({'op': 1, 'd': None}))
                    time.sleep(interval / 1000)
                except Exception as e:
                    if self.connected:
                        self.attempt_reconnect()
                    break
        
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            return
            
        self.heartbeat_thread = threading.Thread(target=heartbeat)
        self.heartbeat_thread.daemon = True
        self.heartbeat_thread.start()
    
    def start_keepalive(self):
        def keepalive():
            while self.connected:
                try:
                    current_time = time.time()
                    if current_time - self.last_keepalive >= 60:
                        if self.voice_connected and self.session_id:
                            self.update_voice_state()
                            self.last_keepalive = current_time
                    
                    time.sleep(30)
                except Exception as e:
                    break
        
        if self.keepalive_thread and self.keepalive_thread.is_alive():
            return
            
        self.keepalive_thread = threading.Thread(target=keepalive)
        self.keepalive_thread.daemon = True
        self.keepalive_thread.start()
    
    def attempt_reconnect(self):
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.connected = False
            return
        
        self.reconnect_attempts += 1
        time.sleep(2 ** self.reconnect_attempts)
        
        try:
            if self.gateway_ws:
                self.gateway_ws.close()
        except:
            pass
        
        self.session_id = None
        self.last_heartbeat_ack = True
        if self.connect_to_gateway() and self.voice_connected:
            if self.current_guild_id and self.current_channel_id:
                self.join_voice_channel(self.current_guild_id, self.current_channel_id)
    
    def connect_to_gateway(self):
        gateway_url = self.get_gateway_url()
        if not gateway_url:
            return False
            
        try:
            self.gateway_ws = websocket.WebSocketApp(
                f"{gateway_url}/?v=9&encoding=json",
                on_message=self.on_gateway_message,
                on_error=self.on_gateway_error,
                on_close=self.on_gateway_close
            )
            
            self.connected = True
            self.last_heartbeat_ack = True
            self.last_keepalive = time.time()
            
            def run_websocket():
                self.gateway_ws.run_forever(
                    ping_interval=30,
                    ping_timeout=10,
                    ping_payload="ping"
                )
            
            ws_thread = threading.Thread(target=run_websocket)
            ws_thread.daemon = True
            ws_thread.start()
            
            for _ in range(100):
                if self.session_id:
                    return True
                time.sleep(0.1)
            
            return False
            
        except Exception as e:
            return False
    
    def update_voice_state(self, guild_id=None, channel_id=None, self_mute=None, self_deaf=None, self_video=None):
        if not self.session_id or not self.connected:
            return False
        
        if guild_id is None:
            guild_id = self.current_guild_id
        if channel_id is None:
            channel_id = self.current_channel_id
        if self_mute is None:
            self_mute = self.self_mute
        if self_deaf is None:
            self_deaf = self.self_deaf
        if self_video is None:
            self_video = self.self_video
        
        voice_state_payload = {
            'op': 4,
            'd': {
                'guild_id': str(guild_id) if guild_id else None,
                'channel_id': str(channel_id) if channel_id else None,
                'self_mute': self_mute,
                'self_deaf': self_deaf,
                'self_video': self_video
            }
        }
        
        try:
            self.gateway_ws.send(json.dumps(voice_state_payload))
            return True
        except Exception as e:
            return False
    
    def send_typing_indicator(self):
        if not self.session_id or not self.connected:
            return False
        
        try:
            presence_payload = {
                'op': 3,
                'd': {
                    'status': 'online',
                    'since': None,
                    'activities': [],
                    'afk': False
                }
            }
            self.gateway_ws.send(json.dumps(presence_payload))
            return True
        except Exception as e:
            return False
    
    def start_stream(self):
        if not self.voice_connected:
            return False, "Not connected to voice channel"
        
        stream_data = {
            'type': 'guild',
            'guild_id': str(self.current_guild_id),
            'channel_id': str(self.current_channel_id),
            'preferred_region': None
        }
        
        response = self.make_request('POST', '/streams', stream_data)
        if response and 'stream_key' in response:
            self.stream_key = response['stream_key']
            self.self_stream = True
            return True, f"Stream started with key: {self.stream_key[:10]}..."
        
        return False, "Failed to start stream"
    
    def stop_stream(self):
        if not self.stream_key:
            return False, "No active stream"
        
        response = self.make_request('DELETE', f'/streams/{self.stream_key}')
        if response:
            self.stream_key = None
            self.self_stream = False
            return True, "Stream stopped"
        
        return False, "Failed to stop stream"
    
    def join_voice_channel(self, guild_id, channel_id):
        if not self.session_id or not self.connected:
            return False
        
        success = self.update_voice_state(guild_id=guild_id, channel_id=channel_id)
        if success:
            self.current_guild_id = guild_id
            
            for _ in range(50):
                if self.voice_connected and self.current_channel_id == str(channel_id):
                    self.last_keepalive = time.time()
                    return True
                time.sleep(0.1)
        
        return False
    
    def leave_voice_channel(self):
        if not self.session_id or not self.current_guild_id:
            return True
        
        if self.stream_key:
            self.stop_stream()
        
        success = self.update_voice_state(channel_id=None)
        if success:
            for _ in range(50):
                if not self.voice_connected:
                    self.current_guild_id = None
                    self.current_channel_id = None
                    return True
                time.sleep(0.1)
        
        return True
    
    def toggle_stream(self):
        if not self.voice_connected:
            return False, "Not connected to voice channel"
        
        if self.self_stream or self.stream_key:
            return self.stop_stream()
        else:
            return self.start_stream()
    
    def toggle_video(self):
        if not self.voice_connected:
            return False, "Not connected to voice channel"
        
        new_video_state = not self.self_video
        success = self.update_voice_state(self_video=new_video_state)
        
        if success:
            time.sleep(0.5)
            action = "enabled" if new_video_state else "disabled"
            return True, f"Camera {action}"
        return False, "Failed to toggle video"
    
    def set_mute(self, muted):
        if not self.voice_connected:
            return False, "Not connected to voice channel"
        
        success = self.update_voice_state(self_mute=muted)
        
        if success:
            action = "muted" if muted else "unmuted"
            return True, f"Microphone {action}"
        return False, "Failed to change mute state"
    
    def set_deafen(self, deafened):
        if not self.voice_connected:
            return False, "Not connected to voice channel"
        
        success = self.update_voice_state(self_deaf=deafened)
        
        if success:
            action = "deafened" if deafened else "undeafened"
            return True, f"Audio {action}"
        return False, "Failed to change deafen state"
    
    def disconnect(self):
        self.connected = False
        if self.voice_connected:
            self.leave_voice_channel()
        if self.gateway_ws:
            try:
                self.gateway_ws.close()
            except:
                pass
        if self.voice_ws:
            try:
                self.voice_ws.close()
            except:
                pass
    
    def is_connected(self):
        return self.connected and self.session_id is not None
    
    def get_status(self):
        if not self.is_connected():
            return f"{Fore.RED}Disconnected{Style.RESET_ALL}"
        elif self.voice_connected:
            status_parts = [f"{Fore.GREEN}Connected to voice{Style.RESET_ALL}"]
            
            if self.self_mute:
                status_parts.append(f"{Fore.YELLOW}[MUTED]{Style.RESET_ALL}")
            if self.self_deaf:
                status_parts.append(f"{Fore.YELLOW}[DEAFENED]{Style.RESET_ALL}")
            if self.self_stream or self.stream_key:
                status_parts.append(f"{Fore.CYAN}[STREAMING]{Style.RESET_ALL}")
            if self.self_video:
                status_parts.append(f"{Fore.MAGENTA}[VIDEO]{Style.RESET_ALL}")
                
            return " ".join(status_parts)
        else:
            return f"{Fore.YELLOW}Connected to gateway{Style.RESET_ALL}"

def list_active_connections():
    if not active_voice_clients:
        print(f"{Fore.YELLOW}No active connections{Style.RESET_ALL}")
        time.sleep(2)
        return
    
    print(f"{Fore.CYAN}Active Connections:{Style.RESET_ALL}")
    for token_index, client in active_voice_clients.items():
        status = client.get_status()
        channel_info = f" (Channel: {client.current_channel_id})" if client.voice_connected else ""
        keepalive_time = int(time.time() - client.last_keepalive)
        print(f"{Fore.YELLOW}Token {token_index}: {client.username}{Style.RESET_ALL} - {status}{channel_info} (Last update: {keepalive_time}s ago)")
    time.sleep(3)

def execute_command(command_data, guild_id, tokens):
    global active_voice_clients
    
    subcommand = command_data['subcommand']
    
    if subcommand == 'list':
        list_active_connections()
        return
    
    if subcommand == 'message':
        token_index = command_data['token_index']
        channel_id = command_data['channel_id']
        message = command_data['message']
        
        if token_index < 0 or token_index >= len(tokens):
            print(f"{Fore.RED}Invalid token index. Available tokens: 0-{len(tokens)-1}{Style.RESET_ALL}")
            time.sleep(2)
            return
        
        if token_index not in active_voice_clients or not active_voice_clients[token_index].is_connected():
            print(f"{Fore.RED}Token {token_index} is not connected{Style.RESET_ALL}")
            time.sleep(2)
            return
        
        client = active_voice_clients[token_index]
        success, result_message = client.send_message(channel_id, message)
        color = Fore.GREEN if success else Fore.RED
        print(f"{color}Token {token_index}: {result_message}{Style.RESET_ALL}")
        time.sleep(2)
        return
    
    token_index = command_data['token_index']
    
    voice_required_commands = ['stream', 'video', 'mute', 'unmute', 'deafen', 'undeafen']
    
    if subcommand in voice_required_commands:
        if token_index not in active_voice_clients or not active_voice_clients[token_index].voice_connected:
            print(f"{Fore.RED}Token {token_index} must be connected to a voice channel first{Style.RESET_ALL}")
            time.sleep(2)
            return
    
    if subcommand in ['connect', 'disconnect']:
        if token_index < 0 or token_index >= len(tokens):
            print(f"{Fore.RED}Invalid token index. Available tokens: 0-{len(tokens)-1}{Style.RESET_ALL}")
            time.sleep(2)
            return
        
        token = tokens[token_index]
        
        if subcommand == 'connect':
            if not command_data['channel_id']:
                print(f"{Fore.RED}Channel ID required for voice connection{Style.RESET_ALL}")
                time.sleep(2)
                return
            
            if token_index in active_voice_clients:
                client = active_voice_clients[token_index]
                if client.is_connected():
                    if client.voice_connected and str(client.current_channel_id) == str(command_data['channel_id']):
                        print(f"{Fore.YELLOW}Token {token_index} already connected to this channel{Style.RESET_ALL}")
                        time.sleep(2)
                        return
                    else:
                        if client.join_voice_channel(guild_id, command_data['channel_id']):
                            print(f"{Fore.GREEN}Token {token_index} successfully switched to voice channel{Style.RESET_ALL}")
                        else:
                            print(f"{Fore.RED}Token {token_index} failed to switch voice channel{Style.RESET_ALL}")
                        time.sleep(2)
                        return
                else:
                    del active_voice_clients[token_index]
            
            client = DiscordVoiceClient(token, token_index)
            
            if client.connect_to_gateway():
                if client.join_voice_channel(guild_id, command_data['channel_id']):
                    print(f"{Fore.GREEN}Token {token_index} successfully connected to voice channel{Style.RESET_ALL}")
                    active_voice_clients[token_index] = client
                    time.sleep(2)
                else:
                    print(f"{Fore.RED}Token {token_index} failed to join voice channel{Style.RESET_ALL}")
                    client.disconnect()
                    time.sleep(2)
            else:
                print(f"{Fore.RED}Token {token_index} failed to connect to gateway{Style.RESET_ALL}")
                time.sleep(2)
        
        elif subcommand == 'disconnect':
            if token_index in active_voice_clients:
                client = active_voice_clients[token_index]
                client.disconnect()
                del active_voice_clients[token_index]
                print(f"{Fore.GREEN}Token {token_index} disconnected successfully{Style.RESET_ALL}")
                time.sleep(2)
            else:
                print(f"{Fore.YELLOW}Token {token_index} is not connected{Style.RESET_ALL}")
                time.sleep(2)
    
    elif subcommand in voice_required_commands:
        client = active_voice_clients[token_index]
        
        if subcommand == 'stream':
            success, message = client.toggle_stream()
        elif subcommand == 'video':
            success, message = client.toggle_video()
        elif subcommand == 'mute':
            success, message = client.set_mute(True)
        elif subcommand == 'unmute':
            success, message = client.set_mute(False)
        elif subcommand == 'deafen':
            success, message = client.set_deafen(True)
        elif subcommand == 'undeafen':
            success, message = client.set_deafen(False)
        
        color = Fore.GREEN if success else Fore.RED
        print(f"{color}Token {token_index}: {message}{Style.RESET_ALL}")
        time.sleep(2)

def main():
    global active_voice_clients
    
    tokens = load_tokens()
    
    if not tokens:
        print(f"{Fore.RED}No tokens found in data/tokens.txt{Style.RESET_ALL}")
        return
    
    display_ansi_art()
    
    guild_id = get_centered_input(f"{Fore.BLUE}{Style.BRIGHT}[ >,,< ] GUILD ID:{Style.RESET_ALL} ")
    
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        display_ansi_art()
        
        if active_voice_clients:
            print(f"\n{Fore.CYAN}Active Connections ({len(active_voice_clients)}):{Style.RESET_ALL}")
            for token_index, client in active_voice_clients.items():
                status = client.get_status()
                channel_info = f" (Channel: {client.current_channel_id})" if client.voice_connected else ""
                keepalive_time = int(time.time() - client.last_keepalive)
                print(f"{Fore.YELLOW}Token {token_index}: {client.username}{Style.RESET_ALL} - {status}{channel_info} (Last update: {keepalive_time}s ago)")
        
        command = get_centered_input(f"{Fore.BLUE}{Style.BRIGHT}[ >,,< ] Command Line:{Style.RESET_ALL} ")
        
        if command.lower() in ['exit', 'quit']:
            if active_voice_clients:
                print(f"{Fore.YELLOW}Disconnecting all active connections...{Style.RESET_ALL}")
                for client in active_voice_clients.values():
                    client.disconnect()
                active_voice_clients.clear()
            break
        
        command_data = parse_command(command)
        
        if not command_data:
            print(f"{Fore.RED}Invalid command format.{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Available commands:{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}  vc connect tok <index> -cid <channel_id>{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}  vc disconnect tok <index>{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}  vc stream tok <index>{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}  vc video tok <index>{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}  vc mute tok <index>{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}  vc unmute tok <index>{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}  vc deafen tok <index>{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}  vc undeafen tok <index>{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}  vc message tok <index> <message> -cid <channel_id>{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}  vc list{Style.RESET_ALL}")
            time.sleep(3)
            continue
        
        try:
            execute_command(command_data, guild_id, tokens)
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Operation cancelled{Style.RESET_ALL}")
            time.sleep(1)
        except Exception as e:
            print(f"{Fore.RED}Runtime error: {str(e)}{Style.RESET_ALL}")
            time.sleep(2)

if __name__ == "__main__":
    main()
