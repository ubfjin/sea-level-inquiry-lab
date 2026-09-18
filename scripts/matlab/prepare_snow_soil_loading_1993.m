%% Prepare ERA5 Snow and Soil Moisture loading for 1993-2022
% Values are already kg/m^2 (numerically mm EWH). Monthly state fields are
% retained; the 2003-2010 per-cell mean is removed later by the SLE builder.
% Antarctic and Greenland ice-sheet support from IB_AIS/IB_GIS_C is excluded.

clearvars;
clc;

scriptDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(scriptDir));
rawDir = fullfile(projectRoot, 'data', 'source', 'barystatic');
preparedDir = fullfile(projectRoot, 'data', 'processed', ...
    'barystatic', 'source_loading');
addpath(fullfile(scriptDir, 'lib'), '-begin');
if ~isfolder(preparedDir)
    mkdir(preparedDir);
end

maskFile = fullfile(rawDir, 'ocean_mask', 'landmask_181361.mat');
maskData = load(maskFile, 'land');
land = logical(maskData.land);
ocean = ~land;
[targetLon, targetColat] = size2sph(ocean);
targetLat = 90 - targetColat(:);
targetLon = targetLon(:);
targetArea = spheregrid(6371000, targetLon, targetColat);

ibFile = fullfile(rawDir, 'IB.mat');
ib = load(ibFile, 'IB_AIS', 'IB_GIS_C');
aisMask = max(abs(ib.IB_AIS), [], 3) > 0;
greenlandMask = max(abs(ib.IB_GIS_C), [], 3) > 0;
iceSheetMask = aisMask | greenlandMask;
assert(isequal(size(iceSheetMask), size(land)));
clear ib;

policyFile = fullfile(preparedDir, 'island_transfer_250km.mat');
cached = load(policyFile, 'policy');
policy = cached.policy;

components = struct( ...
    'sourceFile', { ...
        fullfile(rawDir, ...
            'ERA5_Snow_monthly_19592022_size_181360.mat'), ...
        fullfile(rawDir, ...
            'ERA5_SoilMoisture_monthly_19592022_size_181360.mat')}, ...
    'sourceVariable', {'Snow181360', 'Soil181360'}, ...
    'componentKey', {'seasonal_snow', 'soil_moisture'}, ...
    'componentName', {'Seasonal Snow', 'Soil Moisture'}, ...
    'outputFile', { ...
        fullfile(preparedDir, ...
            'snow_loading_1deg_monthly_199301_202212.nc'), ...
        fullfile(preparedDir, ...
            'soil_moisture_loading_1deg_monthly_199301_202212.nc')});

for component = components
    prepareComponent(component, targetLat, targetLon, targetArea, land, ...
        iceSheetMask, policy, maskFile, ibFile);
end

fprintf('\nPASS: Snow and Soil Moisture prepared for 1993-2022.\n');

function prepareComponent(config, targetLat, targetLon, targetArea, land, ...
        iceSheetMask, policy, maskFile, ibFile)
fprintf('\nLoading %s source once...\n', config.componentName);
source = load(config.sourceFile, config.sourceVariable, ...
    'lat181360', 'lon181360', 'time');
timeNum = datenum(source.time);
positions = find(timeNum >= datenum(1993, 1, 1) & ...
    timeNum <= datenum(2022, 12, 31));
outputTime = timeNum(positions);
assert(numel(positions) == 360 && ...
    strcmp(datestr(outputTime(1), 'yyyy-mm'), '1993-01') && ...
    strcmp(datestr(outputTime(end), 'yyyy-mm'), '2022-12'));
assert(max(abs(source.lat181360(:, 1) - targetLat)) < 1e-10 && ...
    max(abs(source.lon181360(1, :).' - targetLon(1:end-1))) < 1e-10, ...
    'ERA5 source coordinates do not match the unique SLE coordinates.');

createOutput(config, outputTime, targetLat, targetLon, land, ...
    maskFile, ibFile);
status = ncread(config.outputFile, 'preparation_status');
chunkMonths = 24;
sourceValues = source.(config.sourceVariable);
for first = 1:chunkMonths:numel(positions)
    last = min(first + chunkMonths - 1, numel(positions));
    outputIndex = first:last;
    if all(status(outputIndex) == 1)
        continue;
    end
    sourceIndex = positions(outputIndex);
    density = sourceValues(:, :, sourceIndex);
    density361 = cat(2, density, density(:, 1, :));
    excludedMassKg = squeeze(sum( ...
        density361 .* targetArea .* iceSheetMask, [1 2], 'omitnan'));
    densityMatrix = reshape(density361, [], numel(outputIndex));
    densityMatrix(iceSheetMask(:), :) = 0;
    targetMass = reshape(densityMatrix, size(density361)) .* targetArea;
    sourceMassKg = squeeze(sum(targetMass, [1 2], 'omitnan'));
    [landMass, island] = apply_island_mass_policy(targetMass, policy);
    loading = landMass ./ targetArea;
    writeChunk(config.outputFile, first, loading, sourceMassKg, ...
        excludedMassKg, island);
    status(outputIndex) = 1;
    fprintf('%s through %s (%d/%d months)\n', config.componentName, ...
        datestr(outputTime(last), 'yyyy-mm'), last, numel(outputTime));
end
ncwriteatt(config.outputFile, '/', 'processing_status', 'complete');
ncwriteatt(config.outputFile, '/', 'completed_utc', utcTimestamp());
end

function createOutput(config, timeNum, latitude, longitude, land, ...
        maskFile, ibFile)
fileName = config.outputFile;
if isfile(fileName)
    existing = double(ncread(fileName, 'time')) + datenum(1970, 1, 1);
    assert(numel(existing) == numel(timeNum) && ...
        max(abs(existing(:) - timeNum(:))) < 1e-6, ...
        'Existing prepared file has an incompatible time axis.');
    return;
end
nTime = numel(timeNum);
nLat = numel(latitude);
nLon = numel(longitude);
nccreate(fileName, 'time', 'Dimensions', {'time', nTime}, ...
    'Datatype', 'double', 'Format', 'netcdf4');
nccreate(fileName, 'lat', 'Dimensions', {'lat', nLat}, 'Datatype', 'double');
nccreate(fileName, 'lon', 'Dimensions', {'lon', nLon}, 'Datatype', 'double');
nccreate(fileName, 'land_mask', ...
    'Dimensions', {'lat', nLat, 'lon', nLon}, ...
    'Datatype', 'uint8', 'DeflateLevel', 4, 'Shuffle', true);
nccreate(fileName, 'loading', ...
    'Dimensions', {'lat', nLat, 'lon', nLon, 'time', nTime}, ...
    'Datatype', 'single', 'FillValue', single(-9999), ...
    'ChunkSize', [nLat nLon 1], 'DeflateLevel', 4, 'Shuffle', true);
for name = {'source_mass', 'excluded_ice_sheet_mass', ...
        'applied_land_mass', 'relocated_island_mass', ...
        'discarded_far_mass', 'mass_accounting_residual'}
    nccreate(fileName, name{1}, 'Dimensions', {'time', nTime}, ...
        'Datatype', 'double', 'FillValue', -9999, ...
        'DeflateLevel', 4, 'Shuffle', true);
    ncwriteatt(fileName, name{1}, 'units', 'Gt');
end
nccreate(fileName, 'preparation_status', ...
    'Dimensions', {'time', nTime}, 'Datatype', 'uint8', ...
    'FillValue', uint8(0), 'DeflateLevel', 4, 'Shuffle', true);
ncwrite(fileName, 'time', timeNum - datenum(1970, 1, 1));
ncwrite(fileName, 'lat', latitude);
ncwrite(fileName, 'lon', longitude);
ncwrite(fileName, 'land_mask', uint8(land));
ncwriteatt(fileName, 'time', 'units', 'days since 1970-01-01 00:00:00');
ncwriteatt(fileName, 'time', 'calendar', 'gregorian');
ncwriteatt(fileName, 'lat', 'units', 'degrees_north');
ncwriteatt(fileName, 'lon', 'units', 'degrees_east');
ncwriteatt(fileName, 'loading', 'units', 'kg m-2');
ncwriteatt(fileName, 'loading', 'long_name', ...
    sprintf('%s monthly land water-storage state prepared for SLE', ...
    config.componentName));
ncwriteatt(fileName, '/', 'title', ...
    sprintf('Prepared monthly %s loading for the altimetry era', ...
    config.componentName));
ncwriteatt(fileName, '/', 'component_key', config.componentKey);
ncwriteatt(fileName, '/', 'source_file', config.sourceFile);
ncwriteatt(fileName, '/', 'source_variable', config.sourceVariable);
ncwriteatt(fileName, '/', 'source_units', 'kg m-2 (mm EWH)');
ncwriteatt(fileName, '/', 'source_period', '1959-01 through 2022-12');
ncwriteatt(fileName, '/', 'processed_period', '1993-01 through 2022-12');
ncwriteatt(fileName, '/', 'reference_period', ...
    '2003-01 through 2010-12 monthly mean, removed during SLE build');
ncwriteatt(fileName, '/', 'ice_sheet_mask_source', ibFile);
ncwriteatt(fileName, '/', 'ice_sheet_exclusion', ...
    'all nonzero spatial support of IB_AIS or IB_GIS_C');
ncwriteatt(fileName, '/', 'ocean_mask_file', maskFile);
ncwriteatt(fileName, '/', 'longitude_seam_method', ...
    ['source longitude 0 degrees duplicated at 360 degrees; the SLE grid ', ...
    'uses two half-area seam cells']);
ncwriteatt(fileName, '/', 'island_policy', ...
    ['target-ocean loading within 250 km is moved to the nearest land ', ...
    'cell; more distant loading is discarded and recorded']);
ncwriteatt(fileName, '/', 'processing_status', 'incomplete');
ncwriteatt(fileName, '/', 'created_utc', utcTimestamp());
end

function writeChunk(fileName, first, loading, sourceMassKg, ...
        excludedMassKg, island)
nTime = size(loading, 3);
ncwrite(fileName, 'loading', single(loading), [1 1 first]);
ncwrite(fileName, 'source_mass', sourceMassKg(:) / 1e12, first);
ncwrite(fileName, 'excluded_ice_sheet_mass', ...
    excludedMassKg(:) / 1e12, first);
ncwrite(fileName, 'applied_land_mass', ...
    island.appliedMassKg(:) / 1e12, first);
ncwrite(fileName, 'relocated_island_mass', ...
    island.relocatedMassKg(:) / 1e12, first);
ncwrite(fileName, 'discarded_far_mass', ...
    island.discardedMassKg(:) / 1e12, first);
ncwrite(fileName, 'mass_accounting_residual', ...
    island.accountingResidualKg(:) / 1e12, first);
ncwrite(fileName, 'preparation_status', ones(nTime, 1, 'uint8'), first);
end

function value = utcTimestamp()
value = char(datetime('now', 'TimeZone', 'UTC', ...
    'Format', 'yyyy-MM-dd''T''HH:mm:ss''Z'''));
end
