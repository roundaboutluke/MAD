from datetime import datetime
from typing import Optional, List, Dict, Tuple

from sqlalchemy import and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from mapadroid.db.model import Pokestop, TrsVisited, TrsQuest
from mapadroid.geofence.geofenceHelper import GeofenceHelper
from mapadroid.utils.collections import Location
from mapadroid.utils.logging import LoggerEnums, get_logger

logger = get_logger(LoggerEnums.database)


# noinspection PyComparisonWithNone
class PokestopHelper:
    @staticmethod
    async def get(session: AsyncSession, pokestop_id: str) -> Optional[Pokestop]:
        stmt = select(Pokestop).where(Pokestop.pokestop_id == pokestop_id)
        result = await session.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_at_location(session: AsyncSession, location: Location) -> Optional[Pokestop]:
        stmt = select(Pokestop).where(and_(Pokestop.latitude == location.lat,
                                           Pokestop.longitude == location.lng))
        result = await session.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_locations_in_fence(session: AsyncSession, geofence_helper: Optional[GeofenceHelper] = None,
                                     fence=None) -> List[Location]:
        min_lat, min_lon, max_lat, max_lon = geofence_helper.get_polygon_from_fence()
        if fence is not None:
            # TODO: probably gotta fix ST_Contains, ST_GeomFromText and Point...
            stmt = select(Pokestop).where(and_(Pokestop.latitude >= min_lat,
                                               Pokestop.longitude >= min_lon,
                                               Pokestop.latitude <= max_lat,
                                               Pokestop.longitude <= max_lon,
                                               func.ST_Contains(func.ST_GeomFromText(str(fence)),
                                                                func.POINT(Pokestop.latitude, Pokestop.longitude))))
        else:
            stmt = select(Pokestop).where(and_(Pokestop.latitude >= min_lat,
                                          Pokestop.longitude >= min_lon,
                                          Pokestop.latitude <= max_lat,
                                          Pokestop.longitude <= max_lon))
        result = await session.execute(stmt)
        list_of_coords: List[Location] = []
        for pokestop in result.scalars():
            list_of_coords.append(Location(pokestop.latitude, pokestop.longitude))
        if geofence_helper:
            return geofence_helper.get_geofenced_coordinates(list_of_coords)
        else:
            return list_of_coords

    @staticmethod
    async def any_stops_unvisited(session: AsyncSession, geofence_helper: GeofenceHelper, origin: str) -> bool:
        return len(await PokestopHelper.stops_not_visited(session, geofence_helper, origin)) > 0

    @staticmethod
    async def stops_not_visited(session: AsyncSession, geofence_helper: GeofenceHelper, origin: str) -> List[Pokestop]:
        """
        stops_from_db_unvisited
        Args:
            session:
            geofence_helper:
            origin:

        Returns:

        """
        logger.debug3("DbWrapper::any_stops_unvisited called")
        min_lat, min_lon, max_lat, max_lon = geofence_helper.get_polygon_from_fence()
        stmt = select(Pokestop)\
            .join(TrsVisited, and_(Pokestop.pokestop_id == TrsVisited.pokestop_id,
                                   TrsVisited.origin == origin), isouter=True)\
            .where(and_(Pokestop.latitude >= min_lat, Pokestop.longitude >= min_lon,
                        Pokestop.latitude <= max_lat, Pokestop.longitude <= max_lon,
                        TrsVisited.origin == None))
        result = await session.execute(stmt)
        unvisited: List[Pokestop] = []
        for pokestop in result.scalars():
            if geofence_helper.is_coord_inside_include_geofence([pokestop.latitude, pokestop.longitude]):
                unvisited.append(pokestop)
        return unvisited

    @staticmethod
    async def update_location(session: AsyncSession, fort_id: str, location: Location) -> None:
        pokestop: Optional[Pokestop] = await PokestopHelper.get(session, fort_id)
        if not pokestop:
            return
        pokestop.latitude = location.lat
        pokestop.longitude = location.lng
        session.add(pokestop)

    @staticmethod
    async def delete(session: AsyncSession, location: Location) -> None:
        pokestop: Optional[Pokestop] = await PokestopHelper.get_at_location(session, location)
        if pokestop:
            await session.delete(pokestop)

    @staticmethod
    async def get_nearby(session: AsyncSession, location: Location, max_distance: int = 0.5) -> Dict[str, Pokestop]:
        """
        DbWrapper::get_stop_ids_and_locations_nearby
        Args:
            session:
            location:
            max_distance:

        Returns:

        """
        if max_distance < 0:
            logger.warning("Cannot search for stops at negative range...")
            return {}

        stmt = select(Pokestop).where(func.sqrt(func.pow(69.1 * (Pokestop.latitude - location.lat), 2)
                                                + func.pow(69.1 * (location.lng - Pokestop.longitude), 2))
                                        <= max_distance)
        result = await session.execute(stmt)
        stops: Dict[str, Pokestop] = {}
        for pokestop in result.scalars():
            stops[pokestop.pokestop_id] = pokestop
        return stops

    @staticmethod
    async def get_nearby_increasing_range_within_area(session: AsyncSession,
                                                      geofence_helper: GeofenceHelper, origin: str, location: Location,
                                                      limit: int = 20, ignore_spinned: bool = True,
                                                      max_distance: int = 1) -> List[Pokestop]:
        """
        DbWrapper::get_nearest_stops_from_position
        Args:
            session:
            geofence_helper:
            origin:
            location: Location to be used for the search of nearby stops
            limit: Limiting amount of stops returned
            ignore_spinned: Ignore stops that have been spun by the origin
            max_distance:

        Returns:

        """
        logger.debug3("DbWrapper::get_nearest_stops_from_position called")
        min_lat, min_lon, max_lat, max_lon = geofence_helper.get_polygon_from_fence()

        stops_retrieved: List[Pokestop] = []
        select()
        iteration: int = 0
        while (limit > 0 and len(stops_retrieved) < limit) and iteration < 10:
            stops_retrieved.clear()
            where_condition = and_(Pokestop.latitude >= min_lat, Pokestop.longitude >= min_lon,
                                   Pokestop.latitude <= max_lat, Pokestop.longitude <= max_lon,
                                   func.sqrt(func.pow(69.1 * (Pokestop.latitude - location.lat), 2)
                                             + func.pow(69.1 * (location.lng - Pokestop.longitude), 2)) <= max_distance
                                   )
            if ignore_spinned:
                where_condition = and_(TrsVisited.origin == None, where_condition)

            stmt = select(Pokestop,
                          func.sqrt(func.pow(69.1 * (Pokestop.latitude - location.lat), 2)
                                    + func.pow(69.1 * (location.lng - Pokestop.longitude), 2)).label("distance")) \
                .select_from(Pokestop)\
                .join(TrsVisited, and_(Pokestop.pokestop_id == TrsVisited.pokestop_id,
                                       TrsVisited.origin == origin), isouter=True) \
                .where(where_condition).order_by("distance")
            if limit > 0:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            for stop, _distance in result.scalars():
                if not geofence_helper.is_coord_inside_include_geofence([stop.latitude, stop.longitude]):
                    continue
                stops_retrieved.append(stop)


            if len(stops_retrieved) == 0 or limit > 0 and len(stops_retrieved) <= limit:
                logger.debug("No location found or not getting enough locations - increasing distance")
                if iteration >= 7:
                    # setting middle of fence as new startposition
                    lat, lon = geofence_helper.get_middle_from_fence()
                    location = Location(lat, lon)
                else:
                    max_distance += 3
            else:
                # Retrieved some stops (or hit the limit...)
                max_distance += 2
        return stops_retrieved

    @staticmethod
    async def get_with_quests(session: AsyncSession,
                              ne_corner: Optional[Location] = None, sw_corner: Optional[Location] = None,
                              old_ne_corner: Optional[Location] = None, old_sw_corner: Optional[Location] = None,
                              timestamp: Optional[int] = None,
                              fence: Optional[str] = None) -> Dict[int, Tuple[Pokestop, TrsQuest]]:
        """
        quests_from_db
        Args:
            session:
            ne_corner:
            sw_corner:
            old_ne_corner:
            old_sw_corner:
            timestamp:
            fence:

        Returns:

        """
        stmt = select(Pokestop, TrsQuest)\
            .join(TrsQuest, TrsQuest.GUID == Pokestop.pokestop_id, isouter=False)
        where_conditions = []
        # TODO: Verify this works for all timezones...
        where_conditions.append(TrsQuest.quest_timestamp > datetime.today().timestamp())

        if ne_corner and sw_corner:
            where_conditions.append(and_(Pokestop.latitude >= sw_corner.lat,
                                         Pokestop.longitude >= sw_corner.lng,
                                         Pokestop.latitude <= ne_corner.lat,
                                         Pokestop.longitude <= ne_corner.lng))
        if old_ne_corner and old_sw_corner:
            where_conditions.append(and_(Pokestop.latitude >= old_sw_corner.lat,
                                         Pokestop.longitude >= old_sw_corner.lng,
                                         Pokestop.latitude <= old_ne_corner.lat,
                                         Pokestop.longitude <= old_ne_corner.lng))
        if timestamp:
            where_conditions.append(TrsQuest.last_scanned >= datetime.utcfromtimestamp(timestamp))

        if fence:
            where_conditions.append(func.ST_Contains(func.ST_GeomFromText(fence),
                                                     func.POINT(Pokestop.latitude, Pokestop.longitude)))
        stmt = stmt.where(and_(*where_conditions))
        result = await session.execute(stmt)
        stop_with_quest: Dict[int, Tuple[Pokestop, TrsQuest]] = {}
        for (stop, quest) in result.scalars():
            stop_with_quest[stop.pokestop_id] = (stop, quest)
        return stop_with_quest

    @staticmethod
    async def get_in_rectangle(session: AsyncSession,
                              ne_corner: Optional[Location], sw_corner: Optional[Location],
                              old_ne_corner: Optional[Location] = None, old_sw_corner: Optional[Location] = None,
                              timestamp: Optional[int] = None) -> List[Pokestop]:
        stmt = select(Pokestop)
        where_conditions = [and_(Pokestop.latitude >= sw_corner.lat,
                                 Pokestop.longitude >= sw_corner.lng,
                                 Pokestop.latitude <= ne_corner.lat,
                                 Pokestop.longitude <= ne_corner.lng)]
        # TODO: Verify this works for all timezones...
        if old_ne_corner and old_sw_corner:
            where_conditions.append(and_(Pokestop.latitude >= old_sw_corner.lat,
                                         Pokestop.longitude >= old_sw_corner.lng,
                                         Pokestop.latitude <= old_ne_corner.lat,
                                         Pokestop.longitude <= old_ne_corner.lng))
        if timestamp:
            where_conditions.append(TrsQuest.last_scanned >= datetime.utcfromtimestamp(timestamp))
        stmt = stmt.where(and_(*where_conditions))
        result = await session.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_stop_quest(session: AsyncSession) -> List[Tuple[str, int]]:
        """
        DbStatsReader::get_stop_quest
        returns list of tuples containing [date label or NO QUEST, count of stops]
        Args:
            session:

        Returns:

        """
        min_quest_timestamp = func.FROM_UNIXTIME(func.MIN(TrsQuest.quest_timestamp), '%y-%m-%d')
        # LEFT JOIN to fetch stops without quests
        stmt = select(
            func.IF(min_quest_timestamp == None, "No quest",
                    min_quest_timestamp),
            func.COUNT(Pokestop.pokestop_id)
        ).select_from(Pokestop)\
            .join(TrsQuest, TrsQuest.GUID == Pokestop.pokestop_id, isouter=True)\
            .group_by(func.FROM_UNIXTIME(TrsQuest.quest_timestamp, '%y-%m-%d'))
        result = await session.execute(stmt)
        results: List[Tuple[str, int]] = []
        for timestamp_as_str, count in result.scalars():
            results.append((timestamp_as_str, count))
        return results

    @staticmethod
    async def submit_pokestop_visited(session: AsyncSession, location: Location) -> None:
        stmt = update(Pokestop).where(and_(Pokestop.latitude == location.lat,
                                           Pokestop.longitude == location.lng)).values(Pokestop.vi)
        await session.execute(stmt)
