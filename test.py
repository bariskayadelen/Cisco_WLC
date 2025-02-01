import pandas as pd
test_data = [('10.201.129.131', '06.03.118-ANKARA-LISESI', 21)]
df = pd.DataFrame(test_data, columns=['WLC IP Adresi', 'Flexconnect Grup Adı', 'AP Sayısı'])
df.to_excel('test.xlsx', index=False)