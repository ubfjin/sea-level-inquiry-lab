%% Prepare monthly DAM land loading for the altimetry era only
% Output: 1993-01 through 2017-12. The 1992-12 annual field is used only
% as the left interpolation anchor for months before 1993-12.

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

sourceFile = fullfile(rawDir, 'DAM.mat');
maskFile = fullfile(rawDir, 'ocean_mask', 'landmask_181361.mat');
policyFile = fullfile(preparedDir, 'island_transfer_250km.mat');
outputFile = fullfile(preparedDir, ...
    'dam_loading_1deg_monthly_199301_201712.nc');

maskData = load(maskFile, 'land');
land = logical(maskData.land);
ocean = ~land;
[targetLon, targetColat] = size2sph(ocean);
targetLat = 90 - targetColat(:);
targetLon = targetLon(:);
targetArea = spheregrid(6371000, targetLon, targetColat);
cached = load(policyFile, 'policy');
policy = cached.policy;

source = load(sourceFile, 'dam_grid', 'yr_dam');
years = double(source.yr_dam(:));
assert(numel(years) == 118 && years(1) == 1900 && ...
    years(end) == 2017 && all(diff(years) == 1), ...
    'Unexpected DAM source years.');
annualTime = datenum(years, 12, 15);
monthlyTime = datenum(1993, (1:300).', 15);
assert(strcmp(datestr(monthlyTime(1), 'yyyy-mm'), '1993-01') && ...
    strcmp(datestr(monthlyTime(end), 'yyyy-mm'), '2017-12'));

createOutput(outputFile, monthlyTime, targetLat, targetLon, land, ...
    sourceFile, maskFile);
status = ncread(outputFile, 'preparation_status');
if all(status == 1)
    fprintf('All 300 DAM months are already prepared.\n');
    return;
end

damLat = (89.5:-1:-89.5).';
damLon = (0.5:1:359.5).';
fprintf('Conservatively remapping 118 annual DAM fields...\n');
[targetMass, remap] = conservative_remap_regular_mass_series( ...
    source.dam_grid, damLat, damLon, targetLat, targetLon);
[landMass, island] = apply_island_mass_policy(targetMass, policy);
annualLoading = landMass ./ targetArea;
clear targetMass landMass source;

annualDiagnostics = struct( ...
    'source_mass', remap.sourceMassKg(:) / 1e12, ...
    'applied_land_mass', island.appliedMassKg(:) / 1e12, ...
    'relocated_island_mass', island.relocatedMassKg(:) / 1e12, ...
    'discarded_far_mass', island.discardedMassKg(:) / 1e12);

chunkMonths = 24;
for first = 1:chunkMonths:numel(monthlyTime)
    last = min(first + chunkMonths - 1, numel(monthlyTime));
    index = first:last;
    if all(status(index) == 1)
        continue;
    end
    [left, right, fraction] = weights(annualTime, monthlyTime(index));
    loading = annualLoading(:, :, left) .* ...
        reshape(1 - fraction, 1, 1, []) + ...
        annualLoading(:, :, right) .* reshape(fraction, 1, 1, []);
    diagnostics = struct();
    names = fieldnames(annualDiagnostics);
    for k = 1:numel(names)
        values = annualDiagnostics.(names{k});
        diagnostics.(names{k}) = values(left) .* (1 - fraction) + ...
            values(right) .* fraction;
    end
    writeChunk(outputFile, first, loading, diagnostics);
    status(index) = 1;
    fprintf('DAM interpolation through %s (%d/%d months)\n', ...
        datestr(monthlyTime(last), 'yyyy-mm'), last, numel(monthlyTime));
end

ncwriteatt(outputFile, '/', 'processing_status', 'complete');
ncwriteatt(outputFile, '/', 'completed_utc', utcTimestamp());
fprintf('PASS: DAM prepared from 1993-01 through 2017-12.\n');

function createOutput(fileName, timeNum, latitude, longitude, land, ...
        sourceFile, maskFile)
if isfile(fileName)
    existing = double(ncread(fileName, 'time')) + datenum(1970, 1, 1);
    assert(numel(existing) == numel(timeNum) && ...
        max(abs(existing(:) - timeNum(:))) < 1e-6, ...
        'Existing DAM prepared file has an incompatible time axis.');
    return;
end
nTime = numel(timeNum);
nLat = numel(latitude);
nLon = numel(longitude);
fillSingle = single(-9999);
nccreate(fileName, 'time', 'Dimensions', {'time', nTime}, ...
    'Datatype', 'double', 'Format', 'netcdf4');
nccreate(fileName, 'lat', 'Dimensions', {'lat', nLat}, 'Datatype', 'double');
nccreate(fileName, 'lon', 'Dimensions', {'lon', nLon}, 'Datatype', 'double');
nccreate(fileName, 'land_mask', ...
    'Dimensions', {'lat', nLat, 'lon', nLon}, ...
    'Datatype', 'uint8', 'DeflateLevel', 4, 'Shuffle', true);
nccreate(fileName, 'loading', ...
    'Dimensions', {'lat', nLat, 'lon', nLon, 'time', nTime}, ...
    'Datatype', 'single', 'FillValue', fillSingle, ...
    'ChunkSize', [nLat nLon 1], 'DeflateLevel', 4, 'Shuffle', true);
for name = {'source_mass', 'applied_land_mass', ...
        'relocated_island_mass', 'discarded_far_mass', ...
        'mass_accounting_residual'}
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
    'cumulative DAM reservoir land loading prepared for SLE');
ncwriteatt(fileName, '/', 'title', ...
    'Prepared monthly DAM reservoir loading for the altimetry era');
ncwriteatt(fileName, '/', 'summary', ...
    ['Annual DAM fields are assigned to December 15 and linearly ', ...
    'interpolated from 1993-01 through 2017-12. The 1992-12 field is ', ...
    'used only as an interpolation anchor. No temporal extrapolation.']);
ncwriteatt(fileName, '/', 'component_key', 'dam_reservoir_storage');
ncwriteatt(fileName, '/', 'source_file', sourceFile);
ncwriteatt(fileName, '/', 'source_period', '1900-2017 annual');
ncwriteatt(fileName, '/', 'processed_period', '1993-01 through 2017-12');
ncwriteatt(fileName, '/', 'ocean_mask_file', maskFile);
ncwriteatt(fileName, '/', 'remapping', ...
    'spherical cell-area overlap; total mass conserved before island policy');
ncwriteatt(fileName, '/', 'island_policy', ...
    ['target-ocean loading within 250 km is moved to the nearest land ', ...
    'cell; more distant loading is discarded and recorded']);
ncwriteatt(fileName, '/', 'island_maximum_distance_km', 250);
ncwriteatt(fileName, '/', 'processing_status', 'incomplete');
ncwriteatt(fileName, '/', 'created_utc', utcTimestamp());
end

function writeChunk(fileName, first, loading, diagnostics)
nTime = size(loading, 3);
ncwrite(fileName, 'loading', single(loading), [1 1 first]);
ncwrite(fileName, 'source_mass', diagnostics.source_mass, first);
ncwrite(fileName, 'applied_land_mass', ...
    diagnostics.applied_land_mass, first);
ncwrite(fileName, 'relocated_island_mass', ...
    diagnostics.relocated_island_mass, first);
ncwrite(fileName, 'discarded_far_mass', ...
    diagnostics.discarded_far_mass, first);
residual = diagnostics.source_mass - diagnostics.applied_land_mass - ...
    diagnostics.discarded_far_mass;
ncwrite(fileName, 'mass_accounting_residual', residual, first);
ncwrite(fileName, 'preparation_status', ones(nTime, 1, 'uint8'), first);
end

function [left, right, fraction] = weights(anchor, query)
left = zeros(numel(query), 1);
right = zeros(numel(query), 1);
for k = 1:numel(query)
    left(k) = find(anchor <= query(k), 1, 'last');
    right(k) = find(anchor >= query(k), 1, 'first');
end
assert(all(left > 0) && all(right > 0), ...
    'DAM interpolation query lies outside the annual source period.');
same = left == right;
fraction = zeros(numel(query), 1);
fraction(~same) = (query(~same) - anchor(left(~same))) ./ ...
    (anchor(right(~same)) - anchor(left(~same)));
end

function value = utcTimestamp()
value = char(datetime('now', 'TimeZone', 'UTC', ...
    'Format', 'yyyy-MM-dd''T''HH:mm:ss''Z'''));
end
