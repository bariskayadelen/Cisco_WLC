import paramiko
import concurrent.futures
import re
from datetime import datetime
import os
from dotenv import load_dotenv
import time
import pandas as pd
import traceback

load_dotenv()

USERNAME = os.getenv('WLC_USERNAME')
PASSWORD = os.getenv('WLC_PASSWORD')

if not USERNAME or not PASSWORD:
    raise ValueError(".env dosyasında WLC_USERNAME ve/veya WLC_PASSWORD tanımlı değil!")

MAX_WORKERS = 32
OUTPUT_FILE = "wlc_report.xlsx"
PROMPT = r'\(Cisco Controller\)\s*>'
LOCK = concurrent.futures.ThreadPoolExecutor(max_workers=1)
results = []

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

def process_output(ip, output):
    groups = []
    try:
        print(f"Processing output for {ip}")  # Debug
        for line in output.split('\n'):
            cleaned_line = line.replace('\r', '').strip()
            print(f"Raw line: {cleaned_line}")  # Debug
            
            # Geliştirilmiş regex pattern
            match = re.match(r'^(.+?)(\s{2,}|\t)(\d+)$', cleaned_line)
            if match and not cleaned_line.startswith(('---', 'FlexConnect', 'Group', 'Count:')):
                group_name = match.group(1).strip()
                ap_count = match.group(3)
                print(f"Matched: {group_name} - {ap_count}")  # Debug
                groups.append((ip, group_name, ap_count))
        return groups
    except Exception as e:
        print(f"Output processing error for {ip}: {str(e)}")
        traceback.print_exc()
        return []

def ssh_connection(ip):
    try:
        print(f"Connecting to {ip}")  # Debug
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, username=USERNAME, password=PASSWORD, timeout=15)
        
        channel = client.invoke_shell()
        if handle_cisco_prompts(channel):
            commands = [
                'config paging disable',
                'show flexconnect group summary',
                'logout'
            ]
            
            output = ""
            for cmd in commands:
                print(f"Sending command: {cmd} to {ip}")  # Debug
                channel.send(f"{cmd}\n")
                time.sleep(2)  # Artırılmış bekleme süresi
                while True:
                    if channel.recv_ready():
                        data = channel.recv(9999).decode('utf-8')
                        output += data
                        if re.search(PROMPT, data):
                            break
                    else:
                        time.sleep(0.5)
            
            # Verileri işle ve global listeye ekle
            groups = process_output(ip, output)
            print(f"{ip} processed {len(groups)} groups")  # Debug
            
            # Thread-safe veri ekleme
            def add_to_results():
                results.extend(groups)
            LOCK.submit(add_to_results).result()
            
            client.close()
            return f"{ip}: Başarılı - {len(groups)} grup bulundu"
            
    except Exception as e:
        return f"{ip}: Hata - {str(e)}"

def main():
    try:
        with open('wlc_servers.txt', 'r') as f:
            ips = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("Hata: wlc_servers.txt dosyası bulunamadı!")
        return

    # Eski verileri temizle
    results.clear()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(ssh_connection, ip): ip for ip in ips}
        
        for future in concurrent.futures.as_completed(futures):
            ip = futures[future]
            try:
                result = future.result()
                print(f"{ip}: {result}")
            except Exception as e:
                print(f"{ip}: Kritik hata - {str(e)}")

    # Excel'e yaz
    if results:
        try:
            df = pd.DataFrame(results, columns=['WLC IP Adresi', 'Flexconnect Grup Adı', 'AP Sayısı'])
            
            # Excel formatlama
            writer = pd.ExcelWriter(
                OUTPUT_FILE,
                engine='openpyxl',
                engine_kwargs={'options': {'strings_to_numbers': True}}
            )
            
            df.to_excel(writer, index=False)
            
            # Sütun genişlikleri ayarı
            worksheet = writer.sheets['Sheet1']
            worksheet.column_dimensions['A'].width = 15
            worksheet.column_dimensions['B'].width = 40
            worksheet.column_dimensions['C'].width = 12
            
            writer.close()
            print(f"\nExcel dosyası oluşturuldu: {os.path.abspath(OUTPUT_FILE)}")
            
        except Exception as e:
            print(f"\nExcel yazma hatası: {str(e)}")
            traceback.print_exc()
    else:
        print("\nKaydedilecek veri bulunamadı! Muhtemel sebepler:")
        print("- Tüm WLC'lere bağlantı başarısız oldu")
        print("- FlexConnect grup bulunamadı")
        print("- Çıktı formatı beklenenden farklı")

if __name__ == "__main__":
    main()