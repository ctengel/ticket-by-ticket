"""Allow exporting to SVG"""

import xml.etree.ElementTree as ET
import math

RECT_X = 75.0
RECT_Y = 30.0
CIRC_R = "15"
TXT_OFFSET = 22

def deg2num(lat_deg, lon_deg, zoom):
    """Find a tile"""
    # see https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames#Lon./lat._to_tile_numbers_2
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    x_offset = int(256.0 * (((lon_deg + 180.0) / 360.0 * n) - xtile))
    y_offset = int(256.0 * (((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n) - ytile))
    return ((xtile, ytile), (x_offset, y_offset))



def rectsline(length, width):
    """Draw a bunch of rectangles along x axis line"""
    startxs = [x*RECT_X*9.0/8.0 for x in range(length)]
    startys = [y*RECT_Y*9.0/8.0 for y in range(width)]
    allrects = []
    extent = (startxs[-1] + RECT_X, startys[-1] + RECT_Y)
    tx = extent[0] / 2.0
    ty = extent[1] / 2.0
    for x in startxs:
        for y in startys:
            allrects.append([(x-tx,y-ty),
                             (x+RECT_X-tx,y-ty),
                             (x+RECT_X-tx,y+RECT_Y-ty),
                             (x-tx,y+RECT_Y-ty)])
    return allrects

def relpt(midi, angle, pnt):
    """Move a point relative to a certian center"""
    # TODO eliminate angle
    return (midi[0] + pnt[0], midi[1] + pnt[1])

def rectsform(line, rects):
    """Take a bunch of rectangles and draw them along a line"""
    # TODO refactor midpoint from here and draw_map
    midpoint = ((line[0][0] + line[1][0]) / 2.0, (line[0][1] + line[1][1]) / 2.0)
    outrect = []
    for rect in rects:
        myrect = []
        for pnt in rect:
            myrect.append(relpt(midpoint, None, pnt))
        outrect.append(myrect)
    return outrect


def draw_map(my_map, file_name, tile_url, zoom=11, lines=False):
    """Draw map to SVG"""
    extremes = my_map.get_geo_real()
    upper_left, _ = deg2num(extremes[0], extremes[1], zoom)
    lower_right, _ = deg2num(extremes[2], extremes[3], zoom)
    top = ET.Element('svg', {'width': str((lower_right[0] - upper_left[0] + 1) * 256),
                             'height': str((lower_right[1] - upper_left[1] + 1) * 256),
                             'xmlns': 'http://www.w3.org/2000/svg'})
    for tile_x in range(upper_left[0], lower_right[0] + 1):
        for tile_y in range(upper_left[1], lower_right[1] + 1):
            ET.SubElement(top, 'image', {'href': tile_url.format(z=zoom, x=tile_x, y=tile_y),
                                         'height': "256",
                                         'width': "256",
                                         'x': str((tile_x - upper_left[0]) * 256),
                                         'y': str((tile_y - upper_left[1]) * 256)})
    # TODO instead of adding this seperate city_dir datastructure, include pixels in Cities class?
    city_dir = {}
    for city, latlng in my_map.export_cities().items():
        tile, offset = deg2num(latlng[0], latlng[1], zoom)
        city_pxl = ((tile[0] - upper_left[0]) * 256 + offset[0],
                    (tile[1] - upper_left[1]) * 256 + offset[1])
        ET.SubElement(top, 'circle', {'cx': str(city_pxl[0]),
                                      'cy': str(city_pxl[1]),
                                      'r': CIRC_R})
        city_txt = ET.SubElement(top, 'text', {'x': str(city_pxl[0] + TXT_OFFSET),
                                               'y': str(city_pxl[1] + 5)})
        city_txt.text = city
        city_dir[city] = city_pxl
    for route in my_map.export_routes():
        city_locs = [city_dir[x] for x in route['cities']]
        length = route.get('length', 1)
        tracks = route.get('tracks', [None])
        if lines:
            ET.SubElement(top, 'line', {'x1': str(city_locs[0][0]),
                                        'y1': str(city_locs[0][1]),
                                        'x2': str(city_locs[1][0]),
                                        'y2': str(city_locs[1][1]),
                                        'stroke': 'black'})
        rectangles = rectsform([(city_locs[0][0], city_locs[0][1]),
                                (city_locs[1][0], city_locs[1][1])],
                               rectsline(length, len(tracks)))
        # TODO colors
        angle = math.atan2(city_locs[1][1] - city_locs[0][1], city_locs[1][0] - city_locs[0][0])
        midpoint = ((city_locs[0][0] + city_locs[1][0]) / 2.0,
                    (city_locs[0][1] + city_locs[1][1]) / 2.0)
        tracks_g = ET.SubElement(top,
                                 'g',
                                 {'transform': "rotate({} {} {})".format(math.degrees(angle),
                                                                         midpoint[0],
                                                                         midpoint[1])})
        for idx, rect in enumerate(rectangles):
            mycolor = tracks[idx % len(tracks)]
            assert mycolor != "random"
            if not mycolor or mycolor == "blank":
                mycolor = "gray"
            # TODO rectangles instead of polygons
            ET.SubElement(tracks_g,
                          'polygon',
                          {'points': " ".join([",".join([str(y) for y in x]) for x in rect]),
                           'opacity': '0.75',
                           'fill': mycolor})
    tree = ET.ElementTree(element=top)
    ET.indent(tree)
    tree.write(file_name)
