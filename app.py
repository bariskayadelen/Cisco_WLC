import paramiko
import concurrent.futures
import re
from datetime import datetime
import os
from dotenv import load_dotenv
import time
import sqlite3

load_dotenv()

USERNAME = os.getenv('WLC_USERNAME')
PASSWORD = os.getenv('WLC_PASSWORD')

if not USERNAME or not PASSWORD:
    raise ValueError(".env dosyasında WLC_USERNAME ve/veya WLC_PASSWORD tanımlı değil!")

MAX_WORKERS = 32
OUTPUT_FILE = "results.txt"
DB_FILE = "wlc_groups.db"
PROMPT = r'\(Cisco Controller\)\s*>'
LOCK = concurrent.futures.ThreadPoolExecutor(max_workers=1)

def initialize_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS flexconnect_groups
                ([WLC IP Adresi] TEXT, 
                [Flexconnect Grup Adı] TEXT, 
                [AP Sayısı] INTEGER)''')
    conn.commit()
    conn.close()

def handle_cisco_prompts(channel):
    buffer = ""
    while True:
        if channel.recv_ready():
            buffer += channel.recv(9999).decode('utf-8')
            
            if "User:" in buffer:
                channel.send(f"{USERNAME}\n")
                buffer = ""
                time.sleep(1)
            
            if "Password:" in buffer:
                channel.send(f"{PASSWORD}\n")
                buffer = ""
                time.sleep(1)
            
            if re.search(PROMPT, buffer):
                return True
            
        else:
            time.sleep(0.5)

def ssh_connection(ip):
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, username=USERNAME, password=PASSWORD, timeout=10)
        
        channel = client.invoke_shell()
        if handle_cisco_prompts(channel):
            commands = [
                'config paging disable',
                'show flexconnect group summary',
                'exit'
            ]
            
            output = ""
            for cmd in commands:
                channel.send(f"{cmd}\n")
                time.sleep(1)
                while True:
                    if channel.recv_ready():
                        data = channel.recv(9999).decode('utf-8')
                        output += data
                        if re.search(PROMPT, data):
                            break
                    else:
                        time.sleep(0.5)
            
            groups = []
            for line in output.split('\n'):
                cleaned_line = line.replace('\r', '').strip()
                match = re.match(r'^(.+?)\s{2,}(\d+)$', cleaned_line)
                if match and not cleaned_line.startswith(('---', 'FlexConnect', 'Group')):
                    group_name = match.group(1).strip()
                    ap_count = int(match.group(2))
                    groups.append((group_name, ap_count))

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            def write_to_file_and_db():
                # TXT dosyasına yaz
                with open(OUTPUT_FILE, 'a') as f:
                    f.write(f"\n[{timestamp}] WLC {ip}:\n")
                    for group in groups:
                        f.write(f"Grup: {group[0]}, AP Sayısı: {group[1]}\n")
                
                # SQLite'a yaz
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.executemany('''INSERT INTO flexconnect_groups 
                                VALUES (?, ?, ?)''',
                                [(ip, group[0], group[1]) for group in groups])
                conn.commit()
                conn.close()
            
            LOCK.submit(write_to_file_and_db).result()
            client.close()
            return f"{ip}: Başarılı - {len(groups)} grup bulundu"
            
    except Exception as e:
        return f"{ip}: Hata - {str(e)}"

def main():
    initialize_db()
    
    try:
        with open('wlc_servers.txt', 'r') as f:
            ips = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("Hata: wlc_servers.txt dosyası bulunamadı!")
        return

    with open(OUTPUT_FILE, 'w') as f:
        f.write(f"FlexConnect Grup Raporu - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("="*50 + "\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(ssh_connection, ip): ip for ip in ips}
        
        for future in concurrent.futures.as_completed(futures):
            ip = futures[future]
            try:
                result = future.result()
                print(f"{ip}: {result}")
            except Exception as e:
                print(f"{ip}: Kritik hata - {str(e)}")

if __name__ == "__main__":
    main()