%% Prepare Groundwater and DAM land loading on the validated SLE grid
% This stage does not run SLE. It conservatively remaps source surface
% density, applies the agreed <=250 km nearest-land island policy, and
% writes resumable monthly NetCDF inputs. Original files are never changed.

clearvars;
clc;

scriptDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(scriptDir));
sourceDir = fullfile(projectRoot, 'data', 'source', 'barystatic');
outputDir = fullfile(projectRoot, 'data', 'processed', 'barystatic', ...
    'source_loading');
addpath(fullfile(scriptDir, 'lib'), '-begin');
if ~isfolder(outputDir)
    mkdir(outputDir);
end

maskFile = fullfile(sourceDir, 'ocean_mask', 'landmask_181361.mat');
maskData = load(maskFile, 'land');
land = logical(maskData.land);
ocean = ~land;
[targetLon, targetColat] = size2sph(ocean);
targetLat = 90 - targetColat(:);
targetLon = targetLon(:);
targetArea = spheregrid(6371000, targetLon, targetColat);
assert(isequal(size(land), [numel(targetLat), numel(targetLon)]));

policyFile = fullfile(outputDir, 'island_transfer_250km.mat');
if isfile(policyFile)
    cached = load(policyFile, 'policy');
    policy = cached.policy;
    assert(isequal(size(policy.transfer), [numel(land), numel(land)]), ...
        'Cached island transfer has incompatible dimensions.');
else
    fprintf('Building the reusable nearest-land transfer map...\n');
    policy = build_island_mass_transfer( ...
        land, targetLat, targetLon, 250);
    save(policyFile, 'policy', '-v7.3');
end
fprintf(['Island policy: %d ocean cells within 250 km move to land; ', ...
    '%d more-distant ocean cells are discarded when nonzero.\n'], ...
    numel(policy.eligibleOceanIndex), numel(policy.farOceanIndex));

groundwaterOutput = fullfile(outputDir, ...
    'groundwater_loading_1deg_monthly_196001_202304.nc');
prepareGroundwater(fullfile(sourceDir, ...
    'Groundwater_Wada_1960-2010.mat'), groundwaterOutput, ...
    targetLat, targetLon, targetArea, land, policy, maskFile);

damOutput = fullfile(outputDir, ...
    'dam_loading_1deg_monthly_190012_201712.nc');
prepareDam(fullfile(sourceDir, 'DAM.mat'), damOutput, ...
    targetLat, targetLon, targetArea, land, policy, maskFile);

fprintf('\nPASS: prepared monthly land-loading files are complete.\n');
fprintf('Groundwater: %s\n', groundwaterOutput);
fprintf('DAM        : %s\n', damOutput);

function prepareGroundwater(sourceFile, outputFile, targetLat, ...
        targetLon, targetArea, land, policy, maskFile)
fprintf('\nPreparing Groundwater loading...\n');
sourceInfo = whos('-file', sourceFile, 'groundwater');
assert(isequal(sourceInfo.size, [360 720 612]), ...
    'Unexpected Groundwater source dimensions.');
coords = load(sourceFile, 'lat_origin', 'lon_origin', 'time');
rawTime = datenum(coords.time);
rawDate = datevec(rawTime);
assert(rawDate(1, 1) == 1960 && rawDate(1, 2) == 1 && ...
    rawDate(end, 1) == 2010 && rawDate(end, 2) == 12, ...
    'Unexpected Groundwater source period.');

allTime = datenum(1960, (1:(63 * 12 + 4)).', 15);
assert(numel(allTime) == 760 && ...
    strcmp(datestr(allTime(end), 'yyyy-mm'), '2023-04'));
createPreparedFile(outputFile, allTime, targetLat, targetLon, land, ...
    'groundwater', sourceFile, maskFile, ...
    ['Groundwater depletion loading conservatively remapped from 0.5 ', ...
    'degree monthly Wada data. Values after 2010-12 are grid-cell ', ...
    'linear extrapolations of 1991-01 through 2010-12.']);

status = ncread(outputFile, 'preparation_status');
source = matfile(sourceFile);
chunkMonths = 24;
for first = 1:chunkMonths:numel(rawTime)
    last = min(first + chunkMonths - 1, numel(rawTime));
    index = first:last;
    if all(status(index) == 1)
        continue;
    end
    fprintf('Groundwater remap %s through %s...\n', ...
        datestr(allTime(first), 'yyyy-mm'), datestr(allTime(last), 'yyyy-mm'));
    density = source.groundwater(:, :, index);
    [targetMass, remap] = conservative_remap_regular_mass_series( ...
        density, coords.lat_origin, coords.lon_origin, ...
        targetLat, targetLon);
    [landMass, island] = apply_island_mass_policy(targetMass, policy);
    loading = landMass ./ targetArea;
    loading(~land) = 0;
    writePreparedChunk(outputFile, first, loading, ...
        remap.sourceMassKg, island);
    status(index) = 1;
end

status = ncread(outputFile, 'preparation_status');
assert(all(status(1:numel(rawTime)) == 1), ...
    'All observed Groundwater months must precede extrapolation.');
futureIndex = (numel(rawTime) + 1):numel(allTime);
if any(status(futureIndex) ~= 1)
    referenceIndex = find(allTime >= datenum(1991, 1, 1) & ...
        allTime <= datenum(2010, 12, 31));
    assert(numel(referenceIndex) == 240);
    referenceLoading = double(ncread(outputFile, 'loading', ...
        [1 1 referenceIndex(1)], ...
        [numel(targetLat) numel(targetLon) numel(referenceIndex)]));
    referenceLoading = reshape(referenceLoading, [], numel(referenceIndex));
    futureLoading = linearProjection(referenceLoading, ...
        referenceIndex, futureIndex);
    clear referenceLoading;

    diagnosticNames = {'source_mass', 'applied_land_mass', ...
        'relocated_island_mass', 'discarded_far_mass'};
    futureDiagnostics = struct();
    for k = 1:numel(diagnosticNames)
        name = diagnosticNames{k};
        values = double(ncread(outputFile, name));
        projected = linearProjection(values(referenceIndex).', ...
            referenceIndex, futureIndex);
        futureDiagnostics.(name) = projected(:);
    end

    for blockFirst = 1:chunkMonths:numel(futureIndex)
        blockLast = min(blockFirst + chunkMonths - 1, numel(futureIndex));
        local = blockFirst:blockLast;
        index = futureIndex(local);
        if all(status(index) == 1)
            continue;
        end
        slab = reshape(futureLoading(:, local), ...
            [numel(targetLat), numel(targetLon), numel(local)]);
        diagnostics = struct( ...
            'appliedMassKg', futureDiagnostics.applied_land_mass(local) * 1e12, ...
            'relocatedMassKg', futureDiagnostics.relocated_island_mass(local) * 1e12, ...
            'discardedMassKg', futureDiagnostics.discarded_far_mass(local) * 1e12, ...
            'accountingResidualKg', zeros(numel(local), 1));
        writePreparedChunk(outputFile, index(1), slab, ...
            futureDiagnostics.source_mass(local) * 1e12, diagnostics);
    end
end
ncwriteatt(outputFile, '/', 'processing_status', 'complete');
ncwriteatt(outputFile, '/', 'completed_utc', utcTimestamp());
end

function prepareDam(sourceFile, outputFile, targetLat, targetLon, ...
        targetArea, land, policy, maskFile)
fprintf('\nPreparing DAM loading...\n');
source = load(sourceFile, 'dam_grid', 'yr_dam');
years = double(source.yr_dam(:));
assert(numel(years) == 118 && years(1) == 1900 && ...
    years(end) == 2017 && all(diff(years) == 1), ...
    'Unexpected DAM source years.');
annualTime = datenum(years, 12, 15);
monthlyTime = datenum(1900, (12:(118 * 12)).', 15);
assert(strcmp(datestr(monthlyTime(1), 'yyyy-mm'), '1900-12') && ...
    strcmp(datestr(monthlyTime(end), 'yyyy-mm'), '2017-12'));
createPreparedFile(outputFile, monthlyTime, targetLat, targetLon, land, ...
    'dam_reservoir_storage', sourceFile, maskFile, ...
    ['DAM reservoir loading conservatively remapped from annual 1 degree ', ...
    'fields. Annual values are assigned to December 15 and linearly ', ...
    'interpolated between years; no extrapolation is used.']);

status = ncread(outputFile, 'preparation_status');
if all(status == 1)
    ncwriteatt(outputFile, '/', 'processing_status', 'complete');
    return;
end

damLat = (89.5:-1:-89.5).';
damLon = (0.5:1:359.5).';
[targetMass, remap] = conservative_remap_regular_mass_series( ...
    source.dam_grid, damLat, damLon, targetLat, targetLon);
[landMass, island] = apply_island_mass_policy(targetMass, policy);
annualLoading = landMass ./ targetArea;
annualLoading(~land) = 0;
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
    [left, right, fraction] = interpolationWeights( ...
        annualTime, monthlyTime(index));
    slab = annualLoading(:, :, left) .* ...
        reshape(1 - fraction, 1, 1, []) + ...
        annualLoading(:, :, right) .* reshape(fraction, 1, 1, []);
    diagnostics = struct();
    for name = fieldnames(annualDiagnostics).'
        values = annualDiagnostics.(name{1});
        diagnostics.(name{1}) = values(left) .* (1 - fraction) + ...
            values(right) .* fraction;
    end
    islandChunk = struct( ...
        'appliedMassKg', diagnostics.applied_land_mass * 1e12, ...
        'relocatedMassKg', diagnostics.relocated_island_mass * 1e12, ...
        'discardedMassKg', diagnostics.discarded_far_mass * 1e12, ...
        'accountingResidualKg', zeros(numel(index), 1));
    writePreparedChunk(outputFile, first, slab, ...
        diagnostics.source_mass * 1e12, islandChunk);
    status(index) = 1;
    if mod(last, 120) < chunkMonths
        fprintf('DAM interpolation through %s (%d/%d months)\n', ...
            datestr(monthlyTime(last), 'yyyy-mm'), last, numel(monthlyTime));
    end
end
ncwriteatt(outputFile, '/', 'processing_status', 'complete');
ncwriteatt(outputFile, '/', 'completed_utc', utcTimestamp());
end

function createPreparedFile(fileName, timeNum, latitude, longitude, ...
        land, componentKey, sourceFile, maskFile, summary)
if isfile(fileName)
    existingTime = double(ncread(fileName, 'time')) + datenum(1970, 1, 1);
    assert(numel(existingTime) == numel(timeNum) && ...
        max(abs(existingTime(:) - timeNum(:))) < 1e-6, ...
        'Existing prepared file has an incompatible time axis.');
    return;
end
fillSingle = single(-9999);
nTime = numel(timeNum);
nLat = numel(latitude);
nLon = numel(longitude);
nccreate(fileName, 'time', 'Dimensions', {'time', nTime}, ...
    'Datatype', 'double', 'Format', 'netcdf4');
nccreate(fileName, 'lat', 'Dimensions', {'lat', nLat}, 'Datatype', 'double');
nccreate(fileName, 'lon', 'Dimensions', {'lon', nLon}, 'Datatype', 'double');
nccreate(fileName, 'land_mask', 'Dimensions', {'lat', nLat, 'lon', nLon}, ...
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
ncwriteatt(fileName, 'loading', 'long_name', ...
    'cumulative land surface-mass loading prepared for SLE');
ncwriteatt(fileName, 'loading', 'units', 'kg m-2');
ncwriteatt(fileName, 'preparation_status', 'flag_values', uint8([0 1]));
ncwriteatt(fileName, 'preparation_status', 'flag_meanings', ...
    'pending complete');
ncwriteatt(fileName, '/', 'title', ...
    sprintf('Prepared monthly %s land loading', componentKey));
ncwriteatt(fileName, '/', 'summary', summary);
ncwriteatt(fileName, '/', 'component_key', componentKey);
ncwriteatt(fileName, '/', 'source_file', sourceFile);
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

function writePreparedChunk(fileName, first, loading, sourceMassKg, island)
nTime = size(loading, 3);
ncwrite(fileName, 'loading', single(loading), [1 1 first]);
ncwrite(fileName, 'source_mass', sourceMassKg(:) / 1e12, first);
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

function projected = linearProjection(reference, referenceIndex, targetIndex)
reference = double(reference);
x = double(referenceIndex(:));
xc = x - mean(x);
slope = reference * xc / sum(xc .^ 2);
interceptAtMean = mean(reference, 2, 'omitnan');
projected = interceptAtMean + slope * (double(targetIndex(:)).' - mean(x));
end

function [left, right, fraction] = interpolationWeights(anchor, query)
right = arrayfun(@(value) find(anchor >= value, 1, 'first'), query);
left = arrayfun(@(value) find(anchor <= value, 1, 'last'), query);
assert(all(~isnan(left)) && all(~isnan(right)), ...
    'Interpolation query lies outside the annual DAM period.');
same = left == right;
fraction = zeros(numel(query), 1);
fraction(~same) = (query(~same) - anchor(left(~same))) ./ ...
    (anchor(right(~same)) - anchor(left(~same)));
left = left(:);
right = right(:);
end

function value = utcTimestamp()
value = char(datetime('now', 'TimeZone', 'UTC', ...
    'Format', 'yyyy-MM-dd''T''HH:mm:ss''Z'''));
end
