"""Editing TBT maps"""

import argparse
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

def _import(args):
    gmcsv2tbtjson(args.gmcsv, args.tbtjson)

def cli():
    """Command Line editor interface"""
    parser = argparse.ArgumentParser()
    parser.add_argument('tbtjson')
    subparsers = parser.add_subparsers(help='action')

    parser_import = subparsers.add_parser('import')
    parser_import.add_argument('gmcsv')
    parser_import.set_defaults(func=_import)

    args = parser.parse_args()
    args.func(args)
