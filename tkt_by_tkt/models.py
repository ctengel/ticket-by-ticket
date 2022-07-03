"""Data models for Ticket by Ticket"""


class Map:
    """A map"""

    def __init__(self):
        self._cities = {}
        self._routes = []

    def get_city(self, name):
        """Get a city object"""
        return self._cities[name]

    def add_city(self, name):
        """Add a new city to the map"""
        assert name not in self._cities
        self._cities[name] = City(self, name)
        return self._cities[name]

    def del_city(self, name):
        """Remove a city from the map"""
        assert name in self._cities
        assert not self._cities[name].get_routes()
        del self._cities[name]

    def all_city_names(self):
        """All names"""
        return self._cities.keys()

    def export_cities(self):
        """Cities with locations"""
        return {x[0]: list(x[1].where()) for x in self._cities.items()}

    def export_routes(self):
        """Routes with some info"""
        return [x.export() for x in self._routes]

    def add_route(self, cities):
        """Add a route"""
        route = Route(self, [self._cities[x] for x in cities])
        self._routes.append(route)
        return route

    def remove_route(self, cities):
        """Remove a route given two city names"""
        # TODO make private in favor of Route.destruct()
        assert cities[0] != cities[1]
        found = None
        found_index = None
        for index, item in enumerate(self._routes):
            route_cities = item.get_city_names()
            if cities[0] in route_cities and cities[1] in route_cities:
                assert found is None
                assert found_index is None
                found = item
                found_index = index
        assert found
        assert found_index
        found.destruct()
        del self._routes[found_index]

    def get_geo_real(self, border=8):
        """Get extremes of the map in lat and long"""
        latlngs = self.export_cities().values()
        lats = [x[0] for x in latlngs]
        longs = [x[1] for x in latlngs]
        return [max(lats) + (max(lats) - min(lats)) / border,
                min(longs) - (max(longs) - min(longs)) / border,
                min(lats) - (max(lats) - min(lats)) / border,
                max(longs) + (max(longs) - min(longs)) / border]

    def get_routes(self):
        """Get all route objects"""
        return self._routes


class City:
    """A city"""

    def __init__(self, tmap, name):
        self._map = tmap
        self._name = name
        self._latlng = None
        self._routes = []

    def place(self, latlng):
        """Set the location of the city"""
        assert len(latlng) == 2
        self._latlng = latlng

    def where(self):
        """Return tuple with location"""
        return self._latlng

    def get_routes(self):
        """List routes to other cities"""
        ret_routes = {}
        for route in self._routes:
            cities = route.get_city_names()
            assert self._name in cities
            if cities[0] == self._name:
                ret_routes[cities[1]] = route
            else:
                ret_routes[cities[0]] = route
        return ret_routes

    def get_name(self):
        """Name of this city"""
        return self._name

    def _add_route(self, route):
        self._routes.append(route)

    def del_route(self, foreign):
        """PRIVATE"""
        # TODO private?
        for index, route in enumerate(self._routes):
            cities = route.get_city_names()
            assert self._name in cities
            if foreign in cities:
                del self._routes[index]


class Route:
    """A route between two adjacent cities"""

    def __init__(self, tmap, cities):
        assert len(cities) == 2
        self._map = tmap
        self._cities = cities
        self._length = None
        self._tracks = []
        for city in cities:
            city._add_route(self)

    def get_cities(self):
        """Get city objects"""
        return self._cities

    def get_city_names(self):
        """Get city names"""
        return tuple(x.get_name() for x in self._cities)

    def export(self):
        """Return dictionary with info about this route"""
        exp_dict = {'cities': self.get_city_names()}
        if self._length:
            exp_dict['length'] = self._length
        if self._tracks:
            exp_dict['tracks'] = self._tracks
        return exp_dict

    def set_length(self, length):
        """Set the length"""
        assert length
        self._length = length

    def set_tracks(self, tracks):
        """Set tracks with list of colors"""
        assert tracks
        assert tracks[0]
        self._tracks = tracks

    def destruct(self):
        """Called by Map.del_route() to remove from City route lists"""
        # TODO have this be the main entry point instead of Map.del_route()
        self._cities[0].del_route(self._cities[1].get_name())
        self._cities[1].del_route(self._cities[0].get_name())

    def distance(self):
        """Return approximate distance in meters"""
        # TODO more precise estimate
        coords = [x.where() for x in self._cities]
        latdist = (coords[1][0] - coords[0][0]) * 110947.2
        londist = (coords[1][1] - coords[0][1]) * 87843.36
        return (latdist**2 + londist**2)**(0.5)
