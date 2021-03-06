import fiona
import numpy as np
import re

from boundingBox import BoundingBox
from orientedBoundingBox import OrientedBoundingBox
from matplotlib import pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from scipy.spatial import cKDTree
from scipy.spatial import Delaunay, ConvexHull
from shapely.geometry import shape, Polygon, LineString, Point
from shapely.strtree import STRtree
from functions import GetOrientedBoundingBox, GetCornerMaxMin, GetElementsByStorey, GetStoreyElements
from ifcopenshell import open as open_ifc_file


# from rtree import index


def check_boundary(parcel_limit, bldg_limit):
    """ checks if the building respects the parcel's boundary
    input:
    parcel_limit: POLYGON
    bldg_limit: POLYGON
    output: string Pass or Fail
    """
    check = parcel_limit.contains(bldg_limit)
    if check:
        return "Pass", parcel_limit.wkt, bldg_limit.wkt
    else:
        return "Fail", parcel_limit.wkt, bldg_limit.wkt


def shapefile_to_shapely_roads(shape_file):
    roads_geom = {}
    roads_name = {}
    with fiona.open(shape_file) as records:
        for record in records:
            road_id = record['id']
            road_name = record['properties']['STRAAT']
            poly_geom = Polygon(record['geometry']['coordinates'][0])
            roads_geom[road_id] = poly_geom
            roads_name[road_id] = road_name
    return roads_geom, roads_name


def shapefile_to_shapely_parcels(shape_file):
    parcels_geom = []
    with fiona.open(shape_file) as records:
        for record in records:
            poly_geom = Polygon(record['geometry']['coordinates'][0])
            parcels_geom.append(poly_geom)
    return parcels_geom


def get_close_roads(roads_geom, parcel_limit, buffer=500):
    """
    Put roads in a tree and query roads in 500 m buffer
    """
    list_roads = roads_geom.values()
    # Create shapely STRtree
    tree_roads = STRtree(list_roads)
    # map the geometry back to its id
    temp_dict = {}
    for i, road in roads_geom.items():
        temp_dict[id(road)] = i
    query_geom = parcel_limit.buffer(buffer)  # 500 m buffer around parcel can be other value
    chosen_roads = tree_roads.query(query_geom)
    dict_chosen_roads = {}
    for road in chosen_roads:
        dict_chosen_roads[temp_dict[id(road)]] = road
    return dict_chosen_roads


'''def get_close_roads_rtree(roads_geom, parcel_limit, buffer=500):
    """
    Put roads in a tree and query roads in 500 m buffer
    """
    list_roads = roads_geom.values()
    # Create shapely Rtree
    tree_roads = index.Index()
    for i, line in enumerate(list_roads):
        tree_roads.insert(i, line.bounds)
    # map the geometry back to its id
    temp_dict = {}
    for i, road in roads_geom.items():
        temp_dict[id(road)] = i
    query_geom = parcel_limit.buffer(buffer)  # 500 m buffer around parcel can be other value
    chosen_roads = tree_roads.intersection(query_geom.bounds)
    dict_chosen_roads = {}
    for road in chosen_roads:
        dict_chosen_roads[temp_dict[id(road)]] = road
    return chosen_roads'''


def side_to_road(roads, bbox):
    """
    for each side of the building get respective road
    input:
    roads: dictionary of Polygons
    bbox: boundingBox instance
    output:
    dictionary: each side and its respective road
    """
    # for each side get line-normal check road intersection, intersection should be CCW and closest one
    sides = bbox.vertical_sides
    centers, extensions = bbox.get_normal_line()
    centroids = bbox.get_centroid_horizontal()
    # change points from 3D to 2D
    centers = centers[:, [0, 1]]
    extensions = extensions[:, [0, 1]]
    centroid = centroids[:, [0, 1]][0]
    # change to shapely LineString
    shapely_normals = {}
    for i, center in enumerate(centers):
        line = LineString([centroid, extensions[i]])
        shapely_normals[i] = line
    normal_to_road = {}
    for n_id in shapely_normals.keys():
        normal = shapely_normals[n_id]
        distance_to_road = 0
        for road_id in roads.keys():
            road = roads[road_id]
            if normal.intersects(road):
                # if the normal is too short it might not intersect the road find a better a way ensure direction of
                # normal
                line_intersection = normal.intersection(road)
                if line_intersection.type == "MultiLineString":
                    for line in line_intersection:
                        points_intersection = list(line.coords)
                        points_of_normal = list(normal.coords)
                        pt0 = np.array(points_of_normal[0])
                        pt1 = np.array(points_of_normal[1])
                        for point in points_intersection:
                            pt_intersection = np.array(point)
                            # make sure it is pointing away from the bounding box
                            v0 = pt1 - pt0
                            v1 = pt_intersection - pt0
                            check_alignment = np.dot(v0, v1)
                            if check_alignment > 0:
                                # choose closest point
                                dist = np.linalg.norm(v1)
                                if distance_to_road == 0:
                                    normal_to_road[n_id] = road_id
                                    distance_to_road = dist
                                elif dist < distance_to_road:
                                    normal_to_road[n_id] = road_id
                                    distance_to_road = dist
                else:
                    points_intersection = list(line_intersection.coords)
                    points_of_normal = list(normal.coords)
                    pt0 = np.array(points_of_normal[0])
                    pt1 = np.array(points_of_normal[1])
                    for point in points_intersection:
                        pt_intersection = np.array(point)
                        # make sure it is pointing away from the bounding box
                        v0 = pt1 - pt0
                        v1 = pt_intersection - pt0
                        check_alignment = np.dot(v0, v1)
                        if check_alignment > 0:
                            # choose closest point
                            dist = np.linalg.norm(v1)
                            if distance_to_road == 0:
                                normal_to_road[n_id] = road_id
                                distance_to_road = dist
                            elif dist < distance_to_road:
                                normal_to_road[n_id] = road_id
                                distance_to_road = dist
    return normal_to_road


def check_overhang(groundfloor, sides_to_road, sides, roads_name, guideline):
    check = {}
    for side, road_id in sides_to_road.items():
        # get the part of the line that passes the parcel
        side_line_3d = sides[side][0:2]
        temp_line = np.array(side_line_3d)[:, :2]
        side_line_2d = LineString(temp_line.tolist())
        outside_line = side_line_2d.difference(groundfloor)
        # get distance to gf
        furthest_pt = []
        check_dist = 0
        road_name = roads_name[road_id]
        admissible_overhang = guideline[road_name]
        if outside_line.wkt == 'LINESTRING EMPTY':
            check[road_name] = ("Pass", "Admissible overhang: " + str(admissible_overhang),
                                "Overhang: " + "No overhang", side_line_2d.wkt)
        else:
            for point in outside_line.coords:
                pt = Point(point)
                dist_to_gf = groundfloor.exterior.distance(pt)
                if dist_to_gf >= check_dist:
                    check_dist = dist_to_gf
                    furthest_pt = pt
            if admissible_overhang > check_dist:
                check[road_name] = ("Pass", "Admissible overhang: " + str(admissible_overhang),
                                    "Overhang: " + str(check_dist), side_line_2d.wkt)
            else:
                check[road_name] = ("Fail", "Admissible overhang: " + str(admissible_overhang),
                                    "Overhang: " + str(check_dist), side_line_2d.wkt)
    return check


def get_geometry_unchecked_sides(box, sides_facing_roads):
    sides_not_facing_roads = {}
    for i, side in enumerate(box.vertical_sides):
        pt_00 = side[0][:2]
        pt_01 = side[1][:2]
        if i not in sides_facing_roads.keys():
            sides_not_facing_roads[i] = LineString([pt_00, pt_01]).wkt
    return sides_not_facing_roads


def inscribed_r(points):
    pass


'''def alpha_shape_3D(pts, alpha):
    """
    Compute the alpha shape (concave hull) of a set of 3D points.
    Parameters:
        pos - np.array of shape (n,3) points.
        alpha - alpha value.
    return
        outer surface vertex indices, edge indices, and triangle indices
    """
    # get all 3D Delaunay triangles
    tetra = Delaunay(pts)
    tetras_i = tetra.vertices
    tricomb = np.array([(2, 1, 0), (0, 1, 3), (0, 3, 2), (1, 2, 3)])
    all_tr_00 = tetras_i[:, tricomb].reshape(-1, 3)
    all_ = pts[all_tr_00]

    # check which triangles of the convex hull are less than alpha
    # r = inscribed_r(all_)

    tr_check_i = all_tr_00[np.where(r < alpha)]
    # tr_sort_i = tr_check_i[np.arange(np.shape(tr_check_i)[0])[:, np.newaxis], np.argsort(tr_check_i)]
    tr_chosen, count = np.unique(tr_check_i, axis=0, return_counts=True)
    hull_tr = tr_chosen[np.where(count == 1)]

    return hull_tr'''


def read_height_points(shape_file):
    """
    creates dictionary of (x, y) points and their heights
    """
    height_points = []
    heights = []
    with fiona.open(shape_file) as records:
        for record in records:
            point_id = record['properties']['PUNTID']
            if point_id == 0:
                pass
            else:
                height_point = (record['properties']['XCOORDINAA'], record['properties']['YCOORDINAA'])
                height = record['properties']['PEILWAARDE']
                height_points.append(height_point)
                heights.append(height)
    return height_points, heights


def get_height_parcel(parcel_points, points, heights):
    """
    Extracts the height of each point that defines the parcel
    parcel points: points that define the parcel
    points: points from dataset
    heights: height of 'points' from dataset
    """
    point_tree = cKDTree(points)
    # distance and index to nearest point
    dd, ii = point_tree.query(parcel_points, k=1)
    parcel_heights = np.array(heights)[ii]
    return parcel_heights


def check_height(entrance_height, building_height, parcel_heights, maximum_allowed_height):
    """
    checks that the height of the building and the highest parcel point respect the allowed height
    """
    # maybe 80 should be user input
    max_parcel_height = np.amax(parcel_heights)
    height_difference = entrance_height - max_parcel_height
    height_to_check = building_height + height_difference
    if height_to_check <= maximum_allowed_height:
        return "Pass", "Admissible height: " + str(maximum_allowed_height), "Height: " + str(height_to_check)
    else:
        return "Fail", "Admissible height: " + str(maximum_allowed_height), "Height: " + str(height_to_check)


def plot_opaque_cube(x, y, z, dx, dy, dz, polygon, box, sides_facing_roads, checked_results, road_names):
    fig = plt.figure()
    ax = fig.add_subplot(1, 1, 1, projection='3d')
    poly_x, poly_y = polygon.exterior.xy
    plt.plot(poly_x, poly_y)

    """plt.plot([0, 2], [0, 0], color='green')
    plt.plot([2, 2], [0, 1], color='black')
    plt.plot([0, 0], [0, 1], color='black')
    plt.plot([0, 2], [1, 1], color='red')"""
    for i, side in enumerate(box.vertical_sides):
        pt_00 = side[0][:2]
        pt_01 = side[1][:2]
        if i in sides_facing_roads.keys():
            if checked_results[road_names[sides_facing_roads[i]]][0] == 'Pass':
                plt.plot([pt_00[0], pt_01[0]], [pt_00[1], pt_01[1]], color='green')
            else:
                plt.plot([pt_00[0], pt_01[0]], [pt_00[1], pt_01[1]], color='red')
        else:
            plt.plot([pt_00[0], pt_01[0]], [pt_00[1], pt_01[1]], color='black')

    xx = np.linspace(x, x + dx, 2)
    yy = np.linspace(y, y + dy, 2)
    zz = np.linspace(z, z + dz, 2)

    xx, yy = np.meshgrid(xx, yy)

    ax.plot_surface(xx, yy, np.array([[z], [z]]), cmap='gray')
    ax.plot_surface(xx, yy, np.array([[z + dz], [z + dz]]), cmap='gray')

    yy, zz = np.meshgrid(yy, zz)
    ax.plot_surface(x, yy, zz, cmap='gray')
    ax.plot_surface(x + dx, yy, zz, cmap='gray')

    xx, zz = np.meshgrid(xx, zz)
    ax.plot_surface(xx, y, zz, cmap='gray')
    ax.plot_surface(xx, y + dy, zz, cmap='gray')
    # ax.set_xlim3d(-dx, dx*2, 20)
    # ax.set_xlim3d(-dx, dx*2, 20)
    # ax.set_xlim3d(-dx, dx*2, 20)
    plt.show()


def get_gf_floor_idx(storeys_names):
    for i, name in enumerate(storeys_names):
        if name[:2] == '00':
            return i


def get_first_floor_idx(storeys_names):
    for i, name in enumerate(storeys_names):
        if name[:2] == '01':
            return i


def get_georeference(ifc_file):
    origin_point = ()
    true_north = ()
    ifc_dict = {}
    with open(ifc_file, 'r') as f:
        for line in f:
            if line[0] == '#':
                splitting = line.split()
                ifc_dict[splitting[0][:-1]] = splitting[1]
                check_line = splitting[1].split('(')
                if check_line[0] == 'IFCSITE':
                    first_idx = check_line[1].split(',')[5]
                    second_idx = ifc_dict[first_idx].split('(')[1][2:-2]
                    third_idx = ifc_dict[second_idx].split('(')
                    point_idx = third_idx[1].split(',')[0]
                    direction_idx = third_idx[1].split(',')[2][:-2]
                    point = ifc_dict[point_idx].split('(')[1].split(',')
                    origin_point = (float(point[0]), float(point[1]), float(point[2][:-1]))
                    # direction = ifc_dict[direction_idx].split('(')[1].split(',')
                    direction = ifc_dict[direction_idx].split('(')[2].split(',')
                    true_north = (float(direction[0]), float(direction[1]))
                    break
    return np.array(origin_point), np.array(true_north)


def get_angle_from_true_north(true_north):
    origin = np.array([0, 0])
    y = np.array([0, 1])
    origin_north = true_north - origin
    origin_y = y - origin
    cosine_angle = np.dot(origin_north, origin_y) / (np.linalg.norm(origin_north) * np.linalg.norm(origin_y))
    angle = np.arccos(cosine_angle)
    return np.degrees(angle)


def get_georeferenced_point(point, origin_point, true_north):
    rotation_angle = -get_angle_from_true_north(true_north) - 0.2
    newX = point[0] * np.cos(rotation_angle) - point[1] * np.sin(rotation_angle)
    newY = point[0] * np.sin(rotation_angle) + point[1] * np.cos(rotation_angle)
    rotated_point = np.array([newX, newY])
    translated_point = rotated_point + origin_point[:2]
    return translated_point[0], translated_point[1]


def isBetween(a, b, c):
    epsilon = 10 ** (-8)

    crossproduct = (c[1] - a[1]) * (b[0] - a[0]) - (c[0] - a[0]) * (b[1] - a[1])
    if abs(crossproduct) > epsilon:
        return False

    dotproduct = (c[0] - a[0]) * (b[0] - a[0]) + (c[1] - a[1]) * (b[1] - a[1])
    if dotproduct < 0:
        return False

    squaredlengthba = (b[0] - a[0]) * (b[0] - a[0]) + (b[1] - a[1]) * (b[1] - a[1])
    if dotproduct > squaredlengthba:
        return False

    return True


def get_parcel(centroid, parcels):
    chosen_parcels = []
    for parcel in parcels:
        if parcel.contains(centroid):
            chosen_parcels.append(parcel)
    # get smallest polygon
    chosen_parcel = chosen_parcels[0]
    if len(chosen_parcels) > 0:
        for parcel in chosen_parcels[1:]:
            if parcel.within(chosen_parcel):
                chosen_parcel = parcel
    return chosen_parcel


def run_overhang_check(ifc_file, guidelines_file, storey_number=None):
    # get roads guidelines
    guide_lines = guidelines_file['roads']
    # extract georeference from file
    origin_pt, true_n = get_georeference(ifc_file)
    # Building: IFC
    file = open_ifc_file(ifc_file)
    all_storeys_elements, all_storeys_names = GetElementsByStorey(file)
    # get GF
    gf_floor_idx = get_gf_floor_idx(all_storeys_names)
    obb_gf = GetOrientedBoundingBox(all_storeys_elements[gf_floor_idx])
    x_max, x_min, y_max, y_min, z_max, z_min = GetCornerMaxMin(obb_gf[3], obb_gf[4])
    z_min = z_min + origin_pt[2]
    z_max = z_max + origin_pt[2]
    corner_00 = [x_min, y_min]
    corner_01 = [x_max, y_min]
    corner_02 = [x_max, y_max]
    corner_03 = [x_min, y_max]
    corner_00 = get_georeferenced_point(np.array(corner_00), origin_pt, true_n)
    corner_01 = get_georeferenced_point(np.array(corner_01), origin_pt, true_n)
    corner_02 = get_georeferenced_point(np.array(corner_02), origin_pt, true_n)
    corner_03 = get_georeferenced_point(np.array(corner_03), origin_pt, true_n)
    gf = Polygon([corner_00, corner_01, corner_02, corner_03])
    # Get the parcel of project
    centroid_gf = gf.centroid
    parcels = shapefile_to_shapely_parcels("external_datasets/BRK_Rotterdam_Centrum/BRK_SelectieCentrum.shp")
    parcel = get_parcel(centroid_gf, parcels)
    # Remove the underground floors and GF from the list of floors OR get designated floor number
    first_floor_idx = get_first_floor_idx(all_storeys_names)
    all_storeys_elements = all_storeys_elements[first_floor_idx:]
    all_storeys_names = all_storeys_names[first_floor_idx:]
    if storey_number is not None:
        all_storeys_elements = [all_storeys_elements[storey_number - 1]]
        all_storeys_names = all_storeys_names[storey_number - 1]
    # roads
    geom_roads, name_roads = shapefile_to_shapely_roads("external_datasets/Wegvakonderdelen.shp")
    close_roads = get_close_roads(geom_roads, gf)
    # get roads to test against
    query_parcel = parcel.buffer(1)  # 1 m buffer around parcel can be other value
    adjacent_roads = {}
    for i, road in close_roads.items():
        if query_parcel.intersects(road):
            adjacent_roads[i] = road
    lst_all_checks = []
    lst_all_rogues = []
    for storey_elements in all_storeys_elements:
        obb = GetOrientedBoundingBox(storey_elements)
        x_max, x_min, y_max, y_min, z_max, z_min = GetCornerMaxMin(obb[3], obb[4])
        z_min = z_min + origin_pt[2]
        z_max = z_max + origin_pt[2]
        corner_00 = [x_min, y_min]
        corner_01 = [x_max, y_min]
        corner_02 = [x_max, y_max]
        corner_03 = [x_min, y_max]
        corner_00 = get_georeferenced_point(np.array(corner_00), origin_pt, true_n)
        corner_01 = get_georeferenced_point(np.array(corner_01), origin_pt, true_n)
        corner_02 = get_georeferenced_point(np.array(corner_02), origin_pt, true_n)
        corner_03 = get_georeferenced_point(np.array(corner_03), origin_pt, true_n)
        simplified_box = OrientedBoundingBox([corner_00[0], corner_00[1], z_min], [corner_01[0], corner_01[1], z_min],
                                             [corner_02[0], corner_02[1], z_min], [corner_03[0], corner_03[1], z_min],
                                             [corner_00[0], corner_00[1], z_max], [corner_01[0], corner_01[1], z_max],
                                             [corner_02[0], corner_02[1], z_max], [corner_03[0], corner_03[1], z_max])
        sides_roads = side_to_road(adjacent_roads, simplified_box)
        check = check_overhang(gf, sides_roads, simplified_box.vertical_sides, name_roads, guide_lines)
        rogue_sides = get_geometry_unchecked_sides(simplified_box, sides_roads)
        lst_all_checks.append(check)
        lst_all_rogues.append(rogue_sides)
    return lst_all_checks, lst_all_rogues


def run_height_check(ifc_file, guidelines_file):
    # get roads guidelines
    guide_lines = guidelines_file['height']
    # extract georeference from file
    origin_pt, true_n = get_georeference(ifc_file)
    # Building: IFC
    file = open_ifc_file(ifc_file)
    all_storeys_elements, all_storeys_names = GetElementsByStorey(file)
    # get GF
    gf_floor_idx = get_gf_floor_idx(all_storeys_names)
    obb_gf = GetOrientedBoundingBox(all_storeys_elements[gf_floor_idx])
    x_max, x_min, y_max, y_min, z_max, z_min = GetCornerMaxMin(obb_gf[3], obb_gf[4])
    entrance_height = z_min + origin_pt[2]
    corner_00 = [x_min, y_min]
    corner_01 = [x_max, y_min]
    corner_02 = [x_max, y_max]
    corner_03 = [x_min, y_max]
    corner_00 = get_georeferenced_point(np.array(corner_00), origin_pt, true_n)
    corner_01 = get_georeferenced_point(np.array(corner_01), origin_pt, true_n)
    corner_02 = get_georeferenced_point(np.array(corner_02), origin_pt, true_n)
    corner_03 = get_georeferenced_point(np.array(corner_03), origin_pt, true_n)
    gf = Polygon([corner_00, corner_01, corner_02, corner_03])
    # Get the parcel of project
    centroid_gf = gf.centroid
    parcels = shapefile_to_shapely_parcels("external_datasets/BRK_Rotterdam_Centrum/BRK_SelectieCentrum.shp")
    parcel = get_parcel(centroid_gf, parcels)
    parcel_points = list(zip(*parcel.exterior.coords.xy))
    points, heights = read_height_points("external_datasets/UitgiftePeilen/Peil_punten.shp")
    parcel_heights = get_height_parcel(parcel_points, points, heights)
    # get last floor
    obb_last_floor = GetOrientedBoundingBox(all_storeys_elements[-1])
    x_max, x_min, y_max, y_min, z_max, z_min = GetCornerMaxMin(obb_last_floor[3], obb_last_floor[4])
    z_max = z_max + origin_pt[2]
    building_height = z_max - entrance_height
    height_check = check_height(entrance_height, building_height, parcel_heights, guide_lines)
    buffer_gf = gf.buffer(20)
    return height_check, guide_lines, buffer_gf.wkt


def run_boundary_check(ifc_file):
    # extract georeference from file
    origin_pt, true_n = get_georeference(ifc_file)
    # Building: IFC
    file = open_ifc_file(ifc_file)
    all_storeys_elements, all_storeys_names = GetElementsByStorey(file)
    # get GF
    gf_floor_idx = get_gf_floor_idx(all_storeys_names)
    obb_gf = GetOrientedBoundingBox(all_storeys_elements[gf_floor_idx])
    x_max, x_min, y_max, y_min, z_max, z_min = GetCornerMaxMin(obb_gf[3], obb_gf[4])
    corner_00 = [x_min, y_min]
    corner_01 = [x_max, y_min]
    corner_02 = [x_max, y_max]
    corner_03 = [x_min, y_max]
    corner_00 = get_georeferenced_point(np.array(corner_00), origin_pt, true_n)
    corner_01 = get_georeferenced_point(np.array(corner_01), origin_pt, true_n)
    corner_02 = get_georeferenced_point(np.array(corner_02), origin_pt, true_n)
    corner_03 = get_georeferenced_point(np.array(corner_03), origin_pt, true_n)
    gf = Polygon([corner_00, corner_01, corner_02, corner_03])
    # Get the parcel of project
    centroid_gf = gf.centroid
    parcels = shapefile_to_shapely_parcels("external_datasets/BRK_Rotterdam_Centrum/BRK_SelectieCentrum.shp")
    parcel = get_parcel(centroid_gf, parcels)
    boundary_check = check_boundary(parcel, gf)  # test result, parcel polygon wkt, gf polygon wkt
    return boundary_check


guidelines = {
    'roads': {
        'Boompjes': 5,
        'Hertekade': 10
    },
    'height': 100
}

z = run_boundary_check("external_datasets/9252_VRI_Boompjes_constructie_georef.ifc")

y = run_height_check("external_datasets/9252_VRI_Boompjes_constructie_georef.ifc", guidelines)

x = run_overhang_check("external_datasets/9252_VRI_Boompjes_constructie_georef.ifc", guidelines)

'''polya = Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])
polyb = Polygon([(0.5, 0.5), (0.5, 0.8), (0.8, 0.8), (0.8, 0.5)])
#check_boundary(polya, polyb)

polyc = Polygon([(0.5, 0.5), (0.5, 1.5), (1.5, 1.5), (1.5, 0.5)])
#check_boundary(polya, polyc)

# geom_roads, name_roads = shapefile_to_shapely_roads("external_datasets/Wegvakonderdelen.shp")

# height_file = 'external_datasets/UitgiftePeilen/Peil_punten.shp'
# reference_points = read_height_points(height_file)

"""test_points = {
    24: Point([0, 0]),
    34: Point([1, 1]),
    44: Point([2, 2])
}

query_test = get_close_roads(test_points, polyc, 1)"""

# dummy case
box = BoundingBox(0, 2, 0, 1, 2, 5)
parcel = Polygon([(-1, 0.25), (3, 0.25), (3, 0.75), (-1, 0.75), (-1, 0.25)])
road_list = {
    0: Polygon([(-5, -3), (10, -3), (10, -2), (-5, -2), (-5, -3)]),
    1: Polygon([(-5, 3), (10, 3), (10, 4), (-5, 4), (-5, 3)])
}
name_list = {
    0: 'Boompjes',
    1: 'Hertekade'
}
guidelines = {
    'Boompjes': 0.5,
    'Hertekade': 0.2
}
query_test = get_close_roads(road_list, polyc)

sides_roads = side_to_road(road_list, box)
check = check_overhang(parcel, sides_roads, box.vertical_sides, name_list, guidelines)
for road in check.keys():
    print(road)
    print('\t' + check[road][0])
    print('\t' + check[road][1])
    print('\t' + check[road][2])

rogue_sides = get_geometry_unchecked_sides(box, sides_roads)
plot_opaque_cube(0, 0, 2, 2, 1, 5, parcel, box, sides_roads, check, name_list)'''

"""ifc_file = ifcopenshell.open('external_datasets/160035-Boompjes_TVA_gevel_rv19_p.v_georef.ifc')
ifc_elem = functions.GetElementsByStorey(ifc_file)[0][0]
ifc_elem_geom = functions.CreateShape(ifc_elem)[0]
ifc_brep = ifc_elem_geom.brep_data"""
print('Done')
