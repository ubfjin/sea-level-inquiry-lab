function result = build_sle_from_prepared_loading(config)
%BUILD_SLE_FROM_PREPARED_LOADING Build a resumable 1993+ fingerprint file.
% The prepared source must contain cumulative land loading in kg/m^2 on the
% unchanged 181 x 361 SLE grid plus a CF-style monthly time coordinate.

required = {'sourceFile', 'outputFile', 'fingerprintVariable', ...
    'componentKey', 'componentName', 'title', 'summary', ...
    'fingerprintLongName', 'maskFile', 'sleDir', 'harmonicsDir', ...
    'maxDegree', 'expectedEnd'};
for k = 1:numel(required)
    assert(isfield(config, required{k}), ...
        'Missing component configuration: %s', required{k});
end
if ~isfield(config, 'monthLimit')
    config.monthLimit = inf;
end

requiredFiles = {config.sourceFile, config.maskFile, ...
    fullfile(config.sleDir, 'SLE.m'), ...
    fullfile(config.harmonicsDir, 'xyz2plm.m'), ...
    fullfile(config.harmonicsDir, 'plm2xyz.m')};
missing = requiredFiles(~cellfun(@isfile, requiredFiles));
if ~isempty(missing)
    error('PreparedSLE:MissingFile', 'Required file is missing:\n%s', ...
        strjoin(missing, newline));
end

addpath(config.harmonicsDir, '-begin');
addpath(config.sleDir, '-begin');
assert(strcmp(which('SLE'), fullfile(config.sleDir, 'SLE.m')), ...
    'The pinned SLE.m is not first on the MATLAB path.');

mask = load(config.maskFile, 'land');
land = logical(mask.land);
ocean = ~land;
[nativeLon, nativeColat] = size2sph(ocean);
nativeLat = 90 - nativeColat(:);
nativeLon = nativeLon(:);
sourceLat = double(ncread(config.sourceFile, 'lat'));
sourceLon = double(ncread(config.sourceFile, 'lon'));
assert(max(abs(sourceLat(:) - nativeLat)) < 1e-10 && ...
    max(abs(sourceLon(:) - nativeLon)) < 1e-10, ...
    'Prepared loading coordinates do not match the SLE grid.');
assert(isequal(size(land), [numel(sourceLat), numel(sourceLon)]));

sourceStatus = ncread(config.sourceFile, 'preparation_status');
assert(all(sourceStatus == 1), ...
    'Prepared loading is incomplete; finish preparation before SLE.');
allTime = double(ncread(config.sourceFile, 'time')) + datenum(1970, 1, 1);
allTime = allTime(:);
allDate = datevec(allTime);
allMonthIndex = allDate(:, 1) * 12 + allDate(:, 2);
assert(all(diff(allMonthIndex) == 1), ...
    'Prepared source time must be continuous and monthly.');

sourcePositions = find(allTime >= datenum(1993, 1, 1) & ...
    allTime <= datenum(config.expectedEnd));
assert(~isempty(sourcePositions) && ...
    strcmp(datestr(allTime(sourcePositions(1)), 'yyyy-mm'), '1993-01') && ...
    abs(allTime(sourcePositions(end)) - datenum(config.expectedEnd)) <= 1, ...
    'The configured 1993+ fingerprint period is unavailable.');
outputTime = allTime(sourcePositions);
nTime = numel(outputTime);

baselinePositions = find(allTime >= datenum(2003, 1, 1) & ...
    allTime <= datenum(2010, 12, 31));
assert(numel(baselinePositions) == 96, ...
    'Expected 96 months in the 2003-2010 reference period.');
baseline = mean(double(ncread(config.sourceFile, 'loading', ...
    [1 1 baselinePositions(1)], ...
    [numel(sourceLat) numel(sourceLon) numel(baselinePositions)])), ...
    3, 'omitnan');
baselineRelocatedGt = mean(double(ncread(config.sourceFile, ...
    'relocated_island_mass', baselinePositions(1), ...
    numel(baselinePositions))), 'omitnan');
baselineDiscardedGt = mean(double(ncread(config.sourceFile, ...
    'discarded_far_mass', baselinePositions(1), ...
    numel(baselinePositions))), 'omitnan');

[latitude, latitudeOrder] = sort(nativeLat, 'ascend');
uniqueLongitude = nativeLon(1:end-1);
wrappedLongitude = mod(uniqueLongitude + 180, 360) - 180;
[longitude, longitudeOrder] = sort(wrappedLongitude, 'ascend');
landOutput = land(:, 1:end-1);
landOutput = landOutput(latitudeOrder, longitudeOrder);
outputDir = fileparts(config.outputFile);
if ~isfolder(outputDir)
    mkdir(outputDir);
end
if ~isfile(config.outputFile)
    createOutputFile(config, nTime, numel(latitude), numel(longitude));
    writeMetadata(config, latitude, longitude, ...
        outputTime - datenum(1970, 1, 1), landOutput, nTime);
else
    validateExistingOutput(config, nTime);
end

status = ncread(config.outputFile, 'calculation_status');
pending = find(status(:) ~= 1);
if isempty(pending)
    ncwriteatt(config.outputFile, '/', 'processing_status', 'complete');
    result = outputSummary(config.outputFile);
    return;
end
pending = pending(1:min(numel(pending), config.monthLimit));

[areaLon, areaColat] = size2sph(ocean);
cellArea = spheregrid(6371000, areaLon, areaColat);
oceanArea = sum(cellArea(ocean), 'omitnan');
fprintf('\n%s fingerprint: %d total, %d this run\n', ...
    config.componentName, nTime, numel(pending));
runClock = tic;
for k = 1:numel(pending)
    outputPosition = pending(k);
    sourcePosition = sourcePositions(outputPosition);
    loading = double(ncread(config.sourceFile, 'loading', ...
        [1 1 sourcePosition], [numel(sourceLat) numel(sourceLon) 1])) - baseline;
    loading(~isfinite(loading)) = 0;
    assert(max(abs(loading(ocean)), [], 'omitnan') == 0, ...
        'Prepared anomaly contains ocean loading.');

    [fingerprintMetres, updateMetres] = ...
        SLE(ocean, 0, loading, config.maxDegree);
    inputLandMassGt = sum(loading(land) .* cellArea(land), ...
        'omitnan') / 1e12;
    outputOceanMassGt = sum(fingerprintMetres(ocean) .* ...
        cellArea(ocean) .* 1000, 'omitnan') / 1e12;
    residualGt = inputLandMassGt + outputOceanMassGt;
    oceanMeanMm = sum(fingerprintMetres(ocean) .* cellArea(ocean), ...
        'omitnan') / oceanArea * 1000;
    updateMm = updateMetres * 1000;
    assert(abs(residualGt) < 1e-6, ...
        'Mass conservation failed for %s: %.6g Gt.', ...
        datestr(outputTime(outputPosition), 'yyyy-mm'), residualGt);
    assert(abs(oceanMeanMm - updateMm) < 1e-8, ...
        'Ocean mean and SLE update disagree.');

    fingerprintMm = fingerprintMetres(:, 1:end-1) * 1000;
    fingerprintMm = fingerprintMm(latitudeOrder, longitudeOrder);
    fingerprintMm(landOutput) = NaN;
    ncwrite(config.outputFile, config.fingerprintVariable, ...
        reshape(single(fingerprintMm.'), ...
        [numel(longitude), numel(latitude), 1]), ...
        [1 1 outputPosition]);
    ncwrite(config.outputFile, 'eustatic_equivalent', ...
        single(updateMm), outputPosition);
    ncwrite(config.outputFile, 'ocean_mean_fingerprint', ...
        single(oceanMeanMm), outputPosition);
    ncwrite(config.outputFile, 'input_land_mass_anomaly', ...
        inputLandMassGt, outputPosition);
    ncwrite(config.outputFile, 'output_ocean_mass_response', ...
        outputOceanMassGt, outputPosition);
    ncwrite(config.outputFile, 'mass_conservation_residual', ...
        residualGt, outputPosition);
    relocatedGt = double(ncread(config.sourceFile, ...
        'relocated_island_mass', sourcePosition, 1)) - baselineRelocatedGt;
    discardedGt = double(ncread(config.sourceFile, ...
        'discarded_far_mass', sourcePosition, 1)) - baselineDiscardedGt;
    ncwrite(config.outputFile, 'relocated_island_mass_anomaly', ...
        relocatedGt, outputPosition);
    ncwrite(config.outputFile, 'discarded_far_mass_anomaly', ...
        discardedGt, outputPosition);
    ncwrite(config.outputFile, 'calculation_status', ...
        uint8(1), outputPosition);

    elapsed = toc(runClock);
    remainingMinutes = elapsed / k * (numel(pending) - k) / 60;
    fprintf('[%3d/%3d] %s update=%+8.4f mm residual=%+.2e Gt ETA %.1f min\n', ...
        k, numel(pending), datestr(outputTime(outputPosition), 'yyyy-mm'), ...
        updateMm, residualGt, remainingMinutes);
end

status = ncread(config.outputFile, 'calculation_status');
if all(status == 1)
    ncwriteatt(config.outputFile, '/', 'processing_status', 'complete');
    ncwriteatt(config.outputFile, '/', 'completed_utc', utcTimestamp());
else
    ncwriteatt(config.outputFile, '/', 'processing_status', 'incomplete');
end
result = outputSummary(config.outputFile);
end

function createOutputFile(config, nTime, nLatitude, nLongitude)
fillSingle = single(-9999);
nccreate(config.outputFile, 'time', 'Dimensions', {'time', nTime}, ...
    'Datatype', 'double', 'Format', 'netcdf4');
nccreate(config.outputFile, 'lat', 'Dimensions', {'lat', nLatitude}, ...
    'Datatype', 'double');
nccreate(config.outputFile, 'lon', 'Dimensions', {'lon', nLongitude}, ...
    'Datatype', 'double');
nccreate(config.outputFile, 'land_mask', ...
    'Dimensions', {'lon', nLongitude, 'lat', nLatitude}, ...
    'Datatype', 'uint8', 'DeflateLevel', 4, 'Shuffle', true);
nccreate(config.outputFile, config.fingerprintVariable, ...
    'Dimensions', {'lon', nLongitude, 'lat', nLatitude, 'time', nTime}, ...
    'Datatype', 'single', 'FillValue', fillSingle, ...
    'ChunkSize', [nLongitude nLatitude 1], ...
    'DeflateLevel', 4, 'Shuffle', true);
for name = {'eustatic_equivalent', 'ocean_mean_fingerprint'}
    nccreate(config.outputFile, name{1}, ...
        'Dimensions', {'time', nTime}, 'Datatype', 'single', ...
        'FillValue', fillSingle, 'DeflateLevel', 4, 'Shuffle', true);
end
for name = {'input_land_mass_anomaly', 'output_ocean_mass_response', ...
        'mass_conservation_residual', 'relocated_island_mass_anomaly', ...
        'discarded_far_mass_anomaly'}
    nccreate(config.outputFile, name{1}, ...
        'Dimensions', {'time', nTime}, 'Datatype', 'double', ...
        'FillValue', -9999, 'DeflateLevel', 4, 'Shuffle', true);
end
nccreate(config.outputFile, 'calculation_status', ...
    'Dimensions', {'time', nTime}, 'Datatype', 'uint8', ...
    'FillValue', uint8(0), 'DeflateLevel', 4, 'Shuffle', true);
end

function writeMetadata(config, latitude, longitude, timeDays, landMask, nTime)
fileName = config.outputFile;
ncwrite(fileName, 'time', timeDays);
ncwrite(fileName, 'lat', latitude);
ncwrite(fileName, 'lon', longitude);
ncwrite(fileName, 'land_mask', uint8(landMask.'));
ncwriteatt(fileName, 'time', 'standard_name', 'time');
ncwriteatt(fileName, 'time', 'units', 'days since 1970-01-01 00:00:00');
ncwriteatt(fileName, 'time', 'calendar', 'gregorian');
ncwriteatt(fileName, 'lat', 'standard_name', 'latitude');
ncwriteatt(fileName, 'lat', 'units', 'degrees_north');
ncwriteatt(fileName, 'lon', 'standard_name', 'longitude');
ncwriteatt(fileName, 'lon', 'units', 'degrees_east');
ncwriteatt(fileName, config.fingerprintVariable, 'long_name', ...
    config.fingerprintLongName);
ncwriteatt(fileName, config.fingerprintVariable, 'units', 'mm');
ncwriteatt(fileName, config.fingerprintVariable, 'coordinates', ...
    'time lat lon');
for name = {'eustatic_equivalent', 'ocean_mean_fingerprint'}
    ncwriteatt(fileName, name{1}, 'units', 'mm');
end
for name = {'input_land_mass_anomaly', 'output_ocean_mass_response', ...
        'mass_conservation_residual', 'relocated_island_mass_anomaly', ...
        'discarded_far_mass_anomaly'}
    ncwriteatt(fileName, name{1}, 'units', 'Gt');
end
ncwriteatt(fileName, 'calculation_status', 'flag_values', uint8([0 1]));
ncwriteatt(fileName, 'calculation_status', 'flag_meanings', ...
    'pending complete');
ncwriteatt(fileName, '/', 'title', config.title);
ncwriteatt(fileName, '/', 'summary', config.summary);
ncwriteatt(fileName, '/', 'Conventions', 'CF-1.10');
ncwriteatt(fileName, '/', 'component_key', config.componentKey);
ncwriteatt(fileName, '/', 'component', config.componentName);
ncwriteatt(fileName, '/', 'source_file', config.sourceFile);
ncwriteatt(fileName, '/', 'source_loading_units', 'kg m-2 (mm EWH)');
ncwriteatt(fileName, '/', 'reference_period', ...
    '2003-01 through 2010-12 monthly mean');
ncwriteatt(fileName, '/', 'reference_period_months', int32(96));
ncwriteatt(fileName, '/', 'fingerprint_start', '1993-01');
ncwriteatt(fileName, '/', 'fingerprint_months', int32(nTime));
ncwriteatt(fileName, '/', 'sle_maximum_degree', int32(config.maxDegree));
ncwriteatt(fileName, '/', 'sle_model', ...
    'elastic self-attraction and loading; fixed shoreline; no rotation');
ncwriteatt(fileName, '/', 'island_policy', ...
    ['target-ocean loading within 250 km moved to nearest land; ', ...
    'more distant loading discarded and recorded']);
ncwriteatt(fileName, '/', 'processing_status', 'incomplete');
ncwriteatt(fileName, '/', 'created_utc', utcTimestamp());
end

function validateExistingOutput(config, nTime)
assert(numel(ncread(config.outputFile, 'time')) == nTime, ...
    'Existing output has an incompatible time dimension.');
assert(double(ncreadatt(config.outputFile, '/', ...
    'sle_maximum_degree')) == config.maxDegree, ...
    'Existing output used a different SLE degree.');
assert(strcmp(ncreadatt(config.outputFile, '/', 'component_key'), ...
    config.componentKey), 'Existing output is for a different component.');
end

function result = outputSummary(fileName)
status = ncread(fileName, 'calculation_status');
residual = ncread(fileName, 'mass_conservation_residual');
result = struct( ...
    'outputFile', fileName, ...
    'completedMonths', nnz(status == 1), ...
    'totalMonths', numel(status), ...
    'maxMassResidualGt', max(abs(residual(status == 1)), [], 'omitnan'));
end

function value = utcTimestamp()
value = char(datetime('now', 'TimeZone', 'UTC', ...
    'Format', 'yyyy-MM-dd''T''HH:mm:ss''Z'''));
end
