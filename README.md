# ticket-by-ticket
Tools to easily create maps and play a popular game

The purpose is to make custom map generation based on real world geography easy and fun!  The MVP is to be able to generate a board and optionally destination tickets.  From there we want to either design a RESTful API based game engine or find a way to import our custom maps to another game.

## Design

![Design diagram](/design/tbt-design.png)

TBT will consist of the following components/flows:

1. We rely on outside data sources
   - Existing / legacy / planned railroads
   - Actual city and station info
   - Raster graphics of geography, regions, etc
   - Note in future could be a nonexistant/fantasy/elaborated place
   - These outputs go to 2, 4, and 6
2. Map designer
   - Has 1 available
   - Decides where to put actual points/routes data (could be traced over raster or pulled from points) - this becomes 3
   - optionally manipulates map output from 4 to improve
3. points/routes data
   - in JSON
   - from a person 2
   - converts to a map 4
   - also loads to DB 5
4. map generator
   - reads 1 raster and 3 data
   - outputs a single file
   - may also be used by PC game 6
   - may be edited by person 2
   - optionally, prints destination tickets also
5. database / API
   - inputs map data 3
   - interacts with client 6 and robot 7
   - stores game state
6. client
   - uses map data 3
   - interacts with db 5
   - may use 4 map or 1 map
7. robot
   - interacts with db 5
   - may get map data 3
