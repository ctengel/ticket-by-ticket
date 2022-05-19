"""Editing TBT maps"""

from . import models, tbtjson, gmcsv

def gmcsv2tbtjson(gmcsv_file, tbtjson_file):
    """Convert a GM CSV file to native JSON file"""
    with open(gmcsv_file, newline='') as csv_fh:
        csv_data = gmcsv.read_map(csv_fh)
    my_map = models.Map()
    for city, latlng in csv_data.items():
        city_obj = my_map.add_city(city)
        city_obj.place(latlng)
    with open(tbtjson_file, 'w') as json_fh:
        tbtjson.write_map(my_map, json_fh)
