from bs4 import BeautifulSoup
import re
from google.cloud import storage,error_reporting
import hashlib
import ndjson as json
import base64
import unidecode

regexp_price = re.compile('^(\w+)(?:\s*)R\$(?:\s*)(\w+\.?(?:\w+)?\,?(?:\w+)?)')
regexp_markers = re.compile('markers=(.+?)\&')
regex_map = re.compile('\'mapLat\'|\'mapLng\'')

def parse_imovel_page(data):
	'''
	Parse the html page from imoveis web
	:param html_page: page of html
	:return: a dict format value of parsed data
	'''
	error_client = error_reporting.Client()
	try:
		client = storage.Client()
		bucket = client.get_bucket('imoveis-data')
		blob = bucket.get_blob(base64.b64decode(data['data']).decode('utf-8'))
		html_data = blob.download_as_string()
		soup = BeautifulSoup(html_data,'lxml')
		# Parsing the interesting data
		price_block = soup.select('div.block-price-container')
		attrs_block = soup.select('ul.section-icon-features')
		addts_block = soup.select('ul.section-bullets')
		local_block = soup.select('div.article-map')
		scripts = soup.find_all('script')
		filter_scripts = list(filter(lambda val: regex_map.search(val.text),scripts))
		# Transforming data indo a format of interest

		final_tups = []
		description = soup.find('div',id='verDatosDescripcion')
		if description is not None:
			final_tups.append(('descricao',description.text.strip()))		
		try:
			imgs_urls = [img['src']for img in soup.find('div',id='tab-foto-flickity').find_all('img')]
			final_tups.append(('imgs',imgs_urls))
		except:
			error_client.report_exception()


		# Find title
		title_address = soup.find('h2',{'class':'title-location'})
		if title_address is not None:
			address = title_address.find('b')
			neighborhood = title_address.find('span')
			if address is not None:
				final_tups.append(('endereco',address.text.strip()))
			if neighborhood is not None:
				final_tups.append(('bairro',neighborhood.text.strip()))

		if len(addts_block) >= 1:
			audits_final_list = []
			addits_list = [additives.find_all('li') for additives in addts_block]
			[audits_final_list.extend(additive) for additive in addits_list]
			audits_final_list = [unidecode.unidecode(auditive.text.strip()) for auditive in audits_final_list]
			final_tups.append(('additions', audits_final_list))
			
		# Transforming into a final tup
		if len(attrs_block) == 1:
			attrs_list = attrs_block[0].select('li')
			attrs_list = [(attrs.find('span').text.strip(), unidecode.unidecode(attrs.find('b').text.strip())) for attrs in attrs_list]
			final_tups.extend(attrs_list)

		if len(price_block) == 1:
			price_list = price_block[0].text.strip().split('\n')
			price_list = [regexp_price.search(price) for price in price_list if regexp_price.search(price)]
			price_list = [(price_regexp.group(1), float(price_regexp.group(2).replace('.', '').replace(',', '.'))) for
			price_regexp in price_list]
			final_tups.extend(price_list)

		if len(local_block) == 1 or len(filter_scripts) > 0:
			
			if len(filter_scripts) > 0:
				lat_long_script = filter_scripts[0].text
				lat_long = list(filter(lambda val: regex_map.search(val),lat_long_script.split('\n')))
				lat_long = list(map(lambda val: tuple(val.replace(' ','').replace("'",'').replace(',','').replace('mapLat','latitude').replace('mapLng','longitude').strip().split(':')),lat_long))

			else:
				image_url = local_block[0].find('img')
			
				if regexp_markers.search(image_url):
					url_parse = regexp_markers.search(image_url['src']).group(1).split(',')
					lat_long = [float(float_val) for float_val in url_parse]
					lat_long = [('latitude', lat_long[0].replace(',','')), ('longitute', lat_long[1].replace(',',''))]
				
			
			final_tups.extend(lat_long)

			


		json_file = json.dumps({unidecode.unidecode(key).strip().replace(' ','_').lower(): val for key, val in final_tups},ident=-1)
		bucket = client.get_bucket('bigtable-data')
		new_blob = bucket.blob('{hex_name}.json'.format(hex_name=format(data['name']).replace('.html','')))

		new_blob.upload_from_string(json_file)


	except Exception as error:
		error_client = error_reporting.Client()
		error_client.report_exception()