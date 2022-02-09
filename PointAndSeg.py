# Identify tree top and canopy segmentation for LiDAR-derived Canopy Height Model (CHM)
# Anthony Martinez
# Feb 3, 2022

# Import modules
import arcpy
import arcpy.sa
import tempfile
import os.path
import shutil

# Check out any necessary licenses.
arcpy.CheckOutExtension("spatial")

# Set workspace environment
## Output path
#outPath  = r'C:\Users\anthonyjmartinez\Documents\ArcGIS\Projects\LidarTool\PointAndSeg.gdb'
## Save original environment
#aprx = arcpy.mp.ArcGISProject('CURRENT') # or 'CURRENT' in live py console
#origEnvWksp = outPath
#origDefaultGdb = outPath
#origEnvWksp = arcpy.env.workspace
#origDefaultGdb = aprx.defaultGeodatabase

## Make temporary environment
temp_dir = tempfile.mkdtemp()
temp_gdb = "temp.gdb"
arcpy.CreateFileGDB_management(temp_dir, temp_gdb)
arcpy.env.workspace = os.path.join(temp_dir, temp_gdb)
#aprx.defaultGeodatabase = arcpy.env.workspace
arcpy.env.overwriteOutput = True

# Load input data
## Canopy Height Model (raster layer)
chm =  arcpy.Raster(r'C:\Users\anthonyjmartinez\Documents\ArcGIS\Projects\LidarTool\SourdoughCHM2.tif')

## Project area (feature layer)
mask = r'C:\Users\anthonyjmartinez\Documents\ArcGIS\Projects\LidarTool\SSUnit18.shp'

## Should we smooth the CHM?
smCHM = True

## Should we convert CHM height from m to ft?
conCHM = True

## Minimum tree height (in feet)
minTreeHt = 4.5

## Output path
outPath  = r'C:\Users\anthonyjmartinez\Documents\ArcGIS\Projects\LidarTool\PointAndSeg.gdb'

## Clip CHM to project area
CHM_Ext = arcpy.sa.ExtractByMask(in_raster = chm, in_mask_data = mask)

## Smooth CHM if desired
if smCHM == True:
    CHM_Sm = arcpy.sa.FocalStatistics(in_raster=CHM_Ext, neighborhood= "Rectangle 3 3 CELL", statistics_type= "Mean", ignore_nodata="DATA", percentile_value=90)
else:
    CHM_Sm = CHM_Ext

## Convert CHM to feet if necessary
if conCHM == True:
    CHM_Ft = CHM_Sm * 3.281
else:
    CHM_Ft = CHM_Sm

## Set minimum tree height 
CHM_MinHt = arcpy.sa.SetNull(CHM_Ft, CHM_Ft, "VALUE < " + str(minTreeHt))

## Calculate local maxima
CHM_LocalMax = arcpy.sa.FocalStatistics(in_raster = CHM_MinHt, neighborhood = "Rectangle 5 5 CELL", statistics_type = "MAXIMUM", ignore_nodata = "DATA", percentile_value = 90)

## Local maximum = CHM
treeLoc = arcpy.sa.EqualTo(in_raster_or_constant1 = CHM_LocalMax, in_raster_or_constant2 = CHM_MinHt)

## Isolate tree tops
treeLocHt = arcpy.sa.SetNull(in_conditional_raster = treeLoc, in_false_raster_or_constant = CHM_MinHt, where_clause = "Value = 0")

## Raster to point
treeTop = arcpy.conversion.RasterToPoint(in_raster = treeLocHt, out_point_features = "treeTop", raster_field = "Value")

## Rename column to 'Height (ft)'
treeTop = arcpy.management.AlterField(in_table = treeTop, field = "grid_code", new_field_name = "Height", new_field_alias = "Height (ft)")[0]

## Save tree points and canopy height model to desired output location (shapefile if not to gdb)
if outPath[-4:] == ".gdb":
    arcpy.management.CopyFeatures(treeTop, os.path.join(outPath, "TreeTop"))
    arcpy.management.CopyRaster(CHM_Ft, os.path.join(outPath, "CHM_Ft"))
else:
    arcpy.management.CopyFeatures(treeTop, os.path.join(outPath, "TreeTop.shp"))
    arcpy.management.CopyRaster(CHM_Ft, os.path.join(outPath, "CHM_Ft.tif"))

## Reclass tree points to ID number
treeTopReclass = arcpy.sa.ReclassByTable(in_raster = treeLocHt, in_remap_table = treeTop, from_value_field = "Height", to_value_field = "Height", output_value_field = "POINTID", missing_values = "DATA")

## Eulidean allocation
treeTopAlloc = arcpy.sa.EucAllocation(in_source_data = treeTopReclass, source_field = "VALUE", maximum_distance = 40, out_distance_raster = "treeTopDist")
treeTopDist = arcpy.Raster("treeTopDist")

## Create inverse CHM
CHM_Inv = abs(1000 - CHM_Ft)

## Create flow direction raster
CHM_Flow = arcpy.sa.FlowDirection(in_surface_raster = CHM_Inv, force_flow = "NORMAL", flow_direction_type="D8")

## Create watersheds from inverted canopy height
CHM_watershed = arcpy.sa.Watershed(in_flow_direction_raster = CHM_Flow, in_pour_point_data = treeTopReclass, pour_point_field="VALUE")

## Build attibute table
#treeTopAlloc = arcpy.management.BuildRasterAttributeTable(in_raster = treeTopAlloc, overwrite="NONE")[0]

## Watershed Equal To Tree ID
CHM_WsEqAlloc = arcpy.sa.EqualTo(in_raster_or_constant1 = CHM_watershed, in_raster_or_constant2 = treeTopAlloc)

## Get Raster Resolution
Resolution = arcpy.management.GetRasterProperties(in_raster=CHM_Ft, property_type="CELLSIZEX", band_index="")[0]

## Alloc Dist GT 60% Tree Height (Raster Calculator)
DistGT60Hmax = (treeTopDist * float(Resolution) * 3.281 * 0.6) > CHM_Ft

## Join height to treeTopAlloc
treeTopAlloc = arcpy.management.JoinField(in_data = treeTopAlloc, in_field = "Value", join_table = treeTop, join_field = "pointid", fields = ["Height"])[0]

## treeTopAlloc by height instead of ID
treeTopAllocHt = arcpy.sa.Lookup(in_raster = treeTopAlloc, lookup_field = "Height")

## CHM GT 30% Tree Height
Htmx30GTCHM =  (treeTopAllocHt * 0.3) >  CHM_Ft

## Add Segmentation null conditions
SegNull = DistGT60Hmax + Htmx30GTCHM

## Remove null conditions
CanopySegRas = arcpy.sa.SetNull(CHM_WsEqAlloc - SegNull, treeTopAlloc, "VALUE < 1")

## Canopy Segmentation raster to polygon
CanopySeg = arcpy.conversion.RasterToPolygon(in_raster = CanopySegRas, simplify = "SIMPLIFY", raster_field = "Value", create_multipart_features = "SINGLE_OUTER_PART", max_vertices_per_feature = None)

## Simplify Polygon
CanopySeg_Simp = arcpy.cartography.SimplifyPolygon(in_features = CanopySeg, out_feature_class = "in_memory/CanopySeg_Simp", algorithm = "WEIGHTED_AREA", tolerance = "2 Meters", minimum_area = "1 SquareMeters", error_option = "RESOLVE_ERRORS", collapsed_point_option = "NO_KEEP")[0]

## Smooth Polygon
CanopySegmentation = arcpy.cartography.SmoothPolygon(in_features = CanopySeg_Simp, algorithm = "BEZIER_INTERPOLATION", error_option = "FLAG_ERRORS")

## Join, delete, and rename Canopy Seg attribute fields
CanopySegmentation = arcpy.management.JoinField(in_data = CanopySegmentation, in_field = "gridcode", join_table = treeTop, join_field = "pointid", fields = ["Height"])[0]
CanopySegmentation = arcpy.DeleteField_management(CanopySegmentation, ['InPoly_FID', 'SimPgnFlag', 'MaxSimpTol', 'MinSimpTol', 'SmoPgnFlag'])
CanopySegmentation = arcpy.management.AlterField(in_table = CanopySegmentation, field = "gridcode", new_field_name = "Id")[0]
CanopySegmentation = arcpy.management.AlterField(in_table = CanopySegmentation, field = "Height", new_field_name = "Height", new_field_alias = "Height (ft)")[0]

## Save tree points to desired output location (shapefile if not to gdb)
if outPath[-4:] == ".gdb":
    arcpy.management.CopyFeatures(CanopySegmentation, os.path.join(outPath, "CanopySegmentation"))
else:
    arcpy.management.CopyFeatures(CanopySegmentation, os.path.join(outPath, "CanopySegmentation.shp"))



# Reset 
#aprx.defaultGeodatabase = origDefaultGdb
#arcpy.env.workspace = origEnvWksp

# Delete temporary data
shutil.rmtree(temp_dir, True)
