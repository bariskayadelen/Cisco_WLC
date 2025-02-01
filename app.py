import paramiko
import concurrent.futures
import re
from datetime import datetime
import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# Environment değişkenlerini oku
USERNAME = os.getenv('WLC_USERNAME')
PASSWORD = os.getenv('WLC_PASSWORD')

if not USERNAME or not PASSWORD:
    raise ValueError(".env dosyasında WLC_USERNAME ve/veya WLC_PASSWORD tanımlı değil!")

MAX_WORKERS = 32
OUTPUT_FILE = "results.txt"
LOCK = concurrent.futures.ThreadPoolExecutor(max_workers=1)

def ssh_connection(ip):
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, username=USERNAME, password=PASSWORD, timeout=10)
        
        with client.invoke_shell() as shell:
            shell.send('config paging disable\n')
            shell.send('show flexconnect group summary\n')
            shell.send('exit\n')
            
            output = ""
            while True:
                if shell.recv_ready():
                    output += shell.recv(9999).decode('utf-8')
                else:
                    break
        
        groups = re.findall(r'(\S+)\s+\d+\s+\d+\s+\d+\s+(\d+)', output)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        def write_to_file():
            with open(OUTPUT_FILE, 'a') as f:
                f.write(f"\n[{timestamp}] WLC {ip}:\n")
                for group in groups:
                    f.write(f"Grup: {group[0]}, AP Sayısı: {group[1]}\n")
        
        LOCK.submit(write_to_file).result()
        
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

    with open(OUTPUT_FILE, 'w') as f:
        f.write(f"FlexConnect Grup Raporu - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("="*50 + "\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(ssh_connection, ip): ip for ip in ips}
        
        for future in concurrent.futures.as_completed(futures):
            ip = futures[future]
            try:
                result = future.result()
                print(f"{ip}: İşlem tamamlandı - {result}")
            except Exception as e:
                print(f"{ip}: Beklenmeyen hata - {str(e)}")

if __name__ == "__main__":
    main()