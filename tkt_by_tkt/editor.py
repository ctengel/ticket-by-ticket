"""Editing TBT maps"""

import argparse
import os
import random
from . import models, tbtjson, gmcsv, mapsvg

def gmcsv2tbtjson(gmcsv_file, my_map, sync=False, rm_cities=False):
    """Read a GM CSV file"""
    with open(gmcsv_file, newline='') as csv_fh:
        csv_data = gmcsv.read_map(csv_fh)
    existing = my_map.all_city_names()
    found = []
    assert sync == bool(existing)
    for city, latlng in csv_data.items():
        city_obj = None
        if sync and city in existing:
            city_obj = my_map.get_city(city)
        if not city_obj:
            city_obj = my_map.add_city(city)
        city_obj.place(latlng)
        found.append(city)
    for city in existing:
        if city not in found:
            assert rm_cities
            my_map.del_city(city)

def autolengths(my_map):
    """Set all lengths based on shortest run"""
    # TODO allow not clobbering existing lengths
    shortest = min([x.distance() for x in my_map.get_routes()])
    for route in my_map.get_routes():
        route.set_length(int(route.distance() / shortest))

def autocolors(my_map):
    """Automatically randomly assign colors"""
    # TODO allow not colobbering existing colors
    for route in my_map.get_routes():
        num_tracks = len(route.export().get('tracks', [None]))
        if random.getrandbits(1):
            route.set_tracks(["blank"] * num_tracks)
        else:
            route.set_tracks([random.choice(["blue", "red", "orange", "green", "yellow", "purple", "white", "black"]) for _ in range(num_tracks)])


def _import(args, my_map):
    rm_cities = False
    if args.sync:
        # TODO allow deleting cities even if there are routes attached
        rm_cities = args.force
    else:
        # TODO allow force w/o sync to just make a new object and overwrite
        assert not args.force
        assert not my_map.all_city_names()
    gmcsv2tbtjson(args.gmcsv, my_map, args.sync, rm_cities)
    return True

def _route_action(route, length, tracks):
    if length:
        route.set_length(length)
    if tracks:
        route.set_tracks(tracks)

def _con_add(args, my_map):
    assert not (args.interactive and (args.length or args.track))
    my_route = my_map.add_route(args.cities)
    length = args.length
    tracks = args.track
    if args.interactive:
        # TODO implement
        assert False
    _route_action(my_route, length, tracks)
    return True

def _con_mod(args, my_map):
    assert not args.interactive
    # TODO implement interactive
    assert args.length or args.track
    my_route = my_map.get_city(args.cities[0]).get_routes()[args.cities[1]]
    _route_action(my_route, args.length, args.track)
    return True

def _con_del(args, my_map):
    assert not (args.interactive or args.length or args.track)
    my_map.remove_route(args.cities)
    return True

def _con(args, my_map):
    ptrs = {'add': _con_add,
            'mod': _con_mod,
            'del': _con_del}
    return ptrs[args.action](args, my_map)

def _show(args, my_map):
    for city in my_map.all_city_names():
        print("{}:".format(city))
        for adjacent, info in my_map.get_city(city).get_routes().items():
            exp = info.export()
            print('\t- {}, distance {}, tracks {}'.format(adjacent,
                                                          exp.get('length', '?'),
                                                          ','.join(exp.get('tracks', ['?']))))
    return False

def _export(args, my_map):
    # TODO figureout
    mapsvg.draw_map(my_map, args.mapsvg, args.tile_url)
    return False

def _pnt(args, my_map):
    # TODO args.force for delete routes to the city also
    my_map.del_city(args.city)
    return True

def _lengths(args, my_map):
    autolengths(my_map)
    return True

def _colors(args, my_map):
    autocolors(my_map)
    return True

def cli():
    """Command Line editor interface"""
    parser = argparse.ArgumentParser()
    parser.add_argument('tbtjson')
    subparsers = parser.add_subparsers(help='subcommand')

    parser_import = subparsers.add_parser('import')
    parser_import.add_argument('gmcsv')
    parser_import.add_argument('-s', '--sync', action='store_true')
    parser_import.add_argument('-f', '--force', action='store_true')
    parser_import.set_defaults(func=_import)

    parser_con = subparsers.add_parser('con')
    parser_con.add_argument('action', choices=['add', 'mod', 'del'])
    parser_con.add_argument('cities', nargs=2)
    parser_con.add_argument('-i', '--interactive', action='store_true')
    parser_con.add_argument('-l', '--length', type=int)
    parser_con.add_argument('-t', '--track', action='append')
    parser_con.set_defaults(func=_con)

    parser_pnt = subparsers.add_parser('point')
    parser_pnt.add_argument('action', choices=['del'])
    # TODO -f for delete connections also
    parser_pnt.add_argument('city')
    parser_pnt.set_defaults(func=_pnt)

    parser_show = subparsers.add_parser('show')
    parser_show.set_defaults(func=_show)

    parser_import = subparsers.add_parser('export')
    parser_import.add_argument('mapsvg')
    parser_import.add_argument('-t', '--tile-url')
    parser_import.set_defaults(func=_export)

    parser_lengths = subparsers.add_parser('lengths')
    parser_lengths.set_defaults(func=_lengths)

    parser_colors = subparsers.add_parser('colors')
    parser_colors.set_defaults(func=_colors)

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
