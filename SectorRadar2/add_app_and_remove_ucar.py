import yaml

with open('config/themes.yaml', 'r') as f:
    themes = yaml.safe_load(f)

# Add APP to Semiconductor Equipment
if 'APP' not in themes['Semiconductor Equipment']['tickers']:
    themes['Semiconductor Equipment']['tickers'].append('APP')
    print('Added APP to Semiconductor Equipment')
else:
    print('APP already in Semiconductor Equipment')

# Remove UCAR from all themes
for name, data in themes.items():
    if 'UCAR' in data.get('etf', []):
        data['etf'].remove('UCAR')
        print(f'Removed UCAR from {name}')

# Write back
with open('config/themes.yaml', 'w') as f:
    yaml.dump(themes, f, default_flow_style=False, sort_keys=False)

print('Written themes.yaml')