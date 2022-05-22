"""Editing TBT maps"""

import argparse
import os
from . import models, tbtjson, gmcsv

def gmcsv2tbtjson(gmcsv_file, my_map):
    """Read a GM CSV file"""
    with open(gmcsv_file, newline='') as csv_fh:
        csv_data = gmcsv.read_map(csv_fh)
    for city, latlng in csv_data.items():
        city_obj = my_map.add_city(city)
        city_obj.place(latlng)

def _import(args, my_map):
    assert not my_map.all_city_names()
    gmcsv2tbtjson(args.gmcsv, my_map)
    return True

def _con_add(args, my_map):
    my_map.add_route(args.cities)
    return True

def _con_mod(args, my_map):
    return True

def _con_del(args, my_map):
    return True

def _con(args, my_map):
    ptrs = {'add': _con_add,
            'mod': _con_mod,
            'del': _con_del}
    return ptrs[args.action](args, my_map)

def cli():
    """Command Line editor interface"""
    parser = argparse.ArgumentParser()
    parser.add_argument('tbtjson')
    subparsers = parser.add_subparsers(help='subcommand')

    parser_import = subparsers.add_parser('import')
    parser_import.add_argument('gmcsv')
    parser_import.set_defaults(func=_import)

    parser_con = subparsers.add_parser('con')
    parser_con.add_argument('action', choices=['add', 'mod', 'del'])
    parser_con.add_argument('cities', nargs=2)
    parser_con.add_argument('-i', '--interactive', action='store_true')
    parser_con.add_argument('-l', '--length', type=int)
    parser_con.add_argument('-t', '--track', nargs='*')
    parser_con.set_defaults(func=_con)

    args = parser.parse_args()

    try:
        with open(args.tbtjson) as json_fh:
            my_map = tbtjson.read_map(json_fh)
    except IOError:
        assert not os.path.exists(args.tbtjson)
        my_map = models.Map()

    changed = args.func(args, my_map)

    if not changed:
        return

    with open(args.tbtjson, 'w') as json_fh:
        tbtjson.write_map(my_map, json_fh)
