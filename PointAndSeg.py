"""
Tool:               <Lidar tree top and canopy segmentation>
Source Name:        <PointAndSeg>
Version:            <ArcGIS Pro 2.8>
Author:             <Anthony Martinez>
Usage:              <Input canopy height raster and project area (and adjust option parameters) to output point layer with location and heights of tree tops.>
Required Arguments: <parameter0 = Canopy height model (raster layer)>
                    <parameter1 = Clipping feature (feature layer)>
                    <parameter4 = Minimum tree height in feet(double)>
                    <parameter5 = Output workspace (workspace)>
Optional Arguments: <parameter2 = Canopy height model smoothing switch (boolean)>
                    <parameter3 = Convert canopy heights from m to ft (boolean)>
Description:        <Detects and computes the location and height of individual trees within the LiDAR-derived Canopy Height Model (CHM).
                     The algorithm implemented in this function is local maximum with a fixed window size.
                     Adapted from FindTreeCHM tool from "rLiDAR" R package:
                         Carlos Alberto Silva, Nicholas L. Crookston, Andrew T. Hudak, Lee A. Vierling, Carine Klauberg, Adrian Cardil and Caio Hamamura (2021).
                         rLiDAR: LiDAR Data Processing and Visualization.
                         R package version 0.1.5. https://CRAN.R-project.org/package=rLiDAR>
"""
import arcpy


def ScriptTool(parameter0, parameter1, parameter2, parameter3, parameter4, parameter5):
    """ScriptTool function docstring"""
    CHM_Ext = arcpy.sa.ExtractByMask(in_raster = parameter0, in_mask_data = parameter1)
    arcpy.AddMessage("Clipped canopy height model")
    
    ## Smooth CHM if desired
    if parameter2.lower() == 'true':
        CHM_Sm = arcpy.sa.FocalStatistics(in_raster=CHM_Ext, neighborhood= "Rectangle 3 3 CELL", statistics_type= "Mean", ignore_nodata="DATA", percentile_value=90)
        arcpy.AddMessage("Smoothed canopy height model")
    else:
        CHM_Sm = CHM_Ext
    
    ## Convert CHM to feet if necessary
    if parameter3.lower() == 'true':
        CHM_Ft = CHM_Sm * 3.281
        arcpy.AddMessage("Converted canopy heights from m to ft")
    else:
        CHM_Ft = CHM_Sm
    
    ## Set minimum tree height 
    CHM_MinHt = arcpy.sa.SetNull(CHM_Ft, CHM_Ft, "VALUE < " + parameter4)
    arcpy.AddMessage("Set minimum tree height")
    
    ## Calculate local maxima
    CHM_LocalMax = arcpy.sa.FocalStatistics(in_raster = CHM_MinHt, neighborhood = "Rectangle 5 5 CELL", statistics_type = "MAXIMUM", ignore_nodata = "DATA", percentile_value = 90)
    
    ## Local maximum = CHM
    treeLoc = arcpy.sa.EqualTo(in_raster_or_constant1 = CHM_LocalMax, in_raster_or_constant2 = CHM_MinHt)
    
    ## Isolate tree tops
    treeLocHt = arcpy.sa.SetNull(in_conditional_raster = treeLoc, in_false_raster_or_constant = CHM_MinHt, where_clause = "Value = 0")
    
    ## Raster to point
    treeTop = arcpy.conversion.RasterToPoint(in_raster = treeLocHt, out_point_features = "treeTop", raster_field = "Value")
    arcpy.AddMessage("Identified tree tops")

    ## Rename tree top columns
    treeTop = arcpy.management.AlterField(in_table = treeTop, field = "grid_code", new_field_name = "Height", new_field_alias = "Height (ft)")[0]
    treeTop = arcpy.management.AlterField(in_table = treeTop, field = "pointid", new_field_name = "TreeId", new_field_alias = "TreeId")[0]
    
    ## Reclass tree points to ID number
    treeTopReclass = arcpy.sa.ReclassByTable(in_raster = treeLocHt, in_remap_table = treeTop, from_value_field = "Height", to_value_field = "Height", output_value_field = "TreeId", missing_values = "DATA")
    
    ## Eulidean allocation
    treeTopAlloc = arcpy.sa.EucAllocation(in_source_data = treeTopReclass, source_field = "VALUE", maximum_distance = 40, out_distance_raster = "treeTopDist")
    treeTopDist = arcpy.Raster("treeTopDist")
    
    ## Create inverse CHM
    CHM_Inv = abs(1000 - CHM_Ft)
    
    ## Create flow direction raster
    CHM_Flow = arcpy.sa.FlowDirection(in_surface_raster = CHM_Inv, force_flow = "NORMAL", flow_direction_type="D8")
    
    ## Create watersheds from inverted canopy height
    CHM_watershed = arcpy.sa.Watershed(in_flow_direction_raster = CHM_Flow, in_pour_point_data = treeTopReclass, pour_point_field="VALUE")
    arcpy.AddMessage("Created watersheds from inverted canopy height")

    ## Build attibute table
    #treeTopAlloc = arcpy.management.BuildRasterAttributeTable(in_raster = treeTopAlloc, overwrite="NONE")[0]

    ## Watershed Equal To Tree ID
    CHM_WsEqAlloc = arcpy.sa.EqualTo(in_raster_or_constant1 = CHM_watershed, in_raster_or_constant2 = treeTopAlloc)
    
    ## Get Raster Resolution
    Resolution = arcpy.management.GetRasterProperties(in_raster=CHM_Ft, property_type="CELLSIZEX", band_index="")[0]
    
    ## Alloc Dist GT 60% Tree Height (Raster Calculator)
    DistGT60Hmax = (treeTopDist * float(Resolution) * 3.281 * 0.6) > CHM_Ft
    
    ## Join height to treeTopAlloc
    treeTopAlloc = arcpy.management.JoinField(in_data = treeTopAlloc, in_field = "Value", join_table = treeTop, join_field = "TreeId", fields = ["Height"])[0]
    
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
    arcpy.AddMessage("Created canopy segmentations")
    
    ## Simplify Polygon
    CanopySeg_Simp = arcpy.cartography.SimplifyPolygon(in_features = CanopySeg, out_feature_class = "in_memory/CanopySeg_Simp", algorithm = "WEIGHTED_AREA", tolerance = "2 Meters", minimum_area = "1 SquareMeters", error_option = "RESOLVE_ERRORS", collapsed_point_option = "NO_KEEP")[0]
    
    ## Smooth Polygon
    CanopySegmentation = arcpy.cartography.SmoothPolygon(in_features = CanopySeg_Simp, algorithm = "BEZIER_INTERPOLATION", error_option = "FLAG_ERRORS")
    arcpy.AddMessage("Simplified and smoothed canopy segmentation polygons")
    
    ## Join, delete, and rename Canopy Seg attribute fields
    CanopySegmentation = arcpy.management.JoinField(in_data = CanopySegmentation, in_field = "gridcode", join_table = treeTop, join_field = "TreeId", fields = ["Height"])[0]
    CanopySegmentation = arcpy.DeleteField_management(CanopySegmentation, ['Id', 'InPoly_FID', 'SimPgnFlag', 'MaxSimpTol', 'MinSimpTol', 'SmoPgnFlag'])
    CanopySegmentation = arcpy.management.AlterField(in_table = CanopySegmentation, field = "gridcode", new_field_name = "TreeId", new_field_alias = "TreeId")[0]
    CanopySegmentation = arcpy.management.AlterField(in_table = CanopySegmentation, field = "Height", new_field_name = "Height", new_field_alias = "Height (ft)")[0]

    ## Save tree points, canopy segmentation, and canopy height model to desired output location
    if parameter5[-4:] == ".gdb":
        rasterName = arcpy.ValidateTableName("CanopyHeight", parameter5)
        treeTopName = arcpy.ValidateTableName("TreeTop", parameter5)
        canopySegName = arcpy.ValidateTableName("CanopySegmentation", parameter5)
    else:
        rasterName = arcpy.ValidateTableName("CanopyHeight.tif", parameter5)
        treeTopName = arcpy.ValidateTableName("TreeTop.shp", parameter5)
        canopySegName = arcpy.ValidateTableName("CanopySegmentation.shp", parameter5)

    outRaster = os.path.join(parameter5, rasterName)
    outTreeTop = os.path.join(parameter5, treeTopName)
    outCanopySeg = os.path.join(parameter5, canopySegName)

    arcpy.management.CopyRaster(CHM_Ft, outRaster)
    arcpy.management.CopyFeatures(treeTop, outTreeTop)
    arcpy.management.CopyFeatures(CanopySegmentation, outCanopySeg)
    arcpy.AddMessage("Saved files to workspace")

if __name__ == '__main__':
    # ScriptTool parameters
    parameter0 = arcpy.GetParameterAsText(0)
    parameter1 = arcpy.GetParameter(1)
    parameter2 = arcpy.GetParameterAsText(2)
    parameter3 = arcpy.GetParameterAsText(3)
    parameter4 = arcpy.GetParameterAsText(4)
    parameter5 = arcpy.GetParameterAsText(5)
    
    ScriptTool(parameter0, parameter1, parameter2, parameter3, parameter4, parameter5)

