function result = build_sle_component_netcdf(config)
%BUILD_SLE_COMPONENT_NETCDF Create a resumable monthly SLE fingerprint file.
% Source loading is cumulative land mass in kg/m^2 (numerically mm EWH)
% on the validated 181 x 361 global grid.

requiredConfig = {
    'sourceFile', 'sourceVariable', 'timeVariable', 'maskFile', ...
    'outputFile', 'fingerprintVariable', 'componentKey', ...
    'componentName', 'title', 'summary', 'fingerprintLongName', ...
    'sleDir', 'harmonicsDir', 'maxDegree', 'expectedMonths', ...
    'expectedStart', 'expectedEnd'
};
for k = 1:numel(requiredConfig)
    assert(isfield(config, requiredConfig{k}), ...
        'Missing component configuration: %s', requiredConfig{k});
end

requiredFiles = {
    fullfile(config.sleDir, 'SLE.m')
    fullfile(config.harmonicsDir, 'xyz2plm.m')
    fullfile(config.harmonicsDir, 'plm2xyz.m')
    config.sourceFile
    config.maskFile
};
missing = requiredFiles(~cellfun(@isfile, requiredFiles));
if ~isempty(missing)
    error('SLEComponent:MissingFile', 'Required file is missing:\n%s', ...
        strjoin(missing, newline));
end

outputDir = fileparts(config.outputFile);
if ~isfolder(outputDir)
    mkdir(outputDir);
end

addpath(config.harmonicsDir, '-begin');
addpath(config.sleDir, '-begin');
assert(strcmp(which('SLE'), fullfile(config.sleDir, 'SLE.m')), ...
    'The pinned SLE.m is not first on the MATLAB path.');

fprintf('\nLoading %s source fields...\n', config.componentName);
source = load(config.sourceFile, config.sourceVariable, config.timeVariable);
mask = load(config.maskFile, 'land');
assert(isfield(source, config.sourceVariable), ...
    'Source variable %s was not found.', config.sourceVariable);
assert(isfield(source, config.timeVariable), ...
    'Time variable %s was not found.', config.timeVariable);
assert(isfield(mask, 'land'), 'The ocean-mask file must contain land.');

loadingSeries = double(source.(config.sourceVariable));
land = logical(mask.land);
ocean = ~land;
assert(ndims(loadingSeries) == 3, 'Source loading must be a 3-D array.');
assert(isequal(size(land), size(loadingSeries, [1 2])), ...
    'The land mask and source loading horizontal grids do not match.');

timeNum = parseTime(source.(config.timeVariable));
nTime = size(loadingSeries, 3);
assert(numel(timeNum) == nTime, ...
    'The number of dates does not match the number of source fields.');
assert(nTime == config.expectedMonths, ...
    'Expected %d months but found %d.', config.expectedMonths, nTime);
assert(abs(timeNum(1) - datenum(config.expectedStart)) <= 1 && ...
    abs(timeNum(end) - datenum(config.expectedEnd)) <= 1, ...
    'The source period does not match the configured period.');

dateVectors = datevec(timeNum);
monthIndex = dateVectors(:, 1) * 12 + dateVectors(:, 2);
assert(all(diff(monthIndex) == 1), ...
    'The source time axis must be continuous and monthly.');

baselineIndex = timeNum >= datenum(2003, 1, 1) & ...
    timeNum <= datenum(2010, 12, 31);
assert(nnz(baselineIndex) == 96, ...
    'Expected 96 months in the 2003-2010 reference period.');
baseline = mean(loadingSeries(:, :, baselineIndex), 3, 'omitnan');

[sourceLongitude, sourceColatitude] = size2sph(ocean);
sourceLatitude = 90 - sourceColatitude(:);
sourceLongitude = sourceLongitude(:);
assert(numel(sourceLatitude) == 181 && numel(sourceLongitude) == 361, ...
    'Expected the validated 181 x 361 global SLE grid.');

seamDifference = max(abs(loadingSeries(:, 1, :) - ...
    loadingSeries(:, end, :)), [], 'all', 'omitnan');
fprintf('Source 0/360-degree maximum difference: %.6g kg/m^2\n', ...
    seamDifference);
% Do not alter either boundary column. SLE receives the original validated
% 181 x 361 loading and mask exactly as stored. Only the exported web grid
% omits the final coordinate to avoid displaying the same meridian twice.

[latitude, latitudeOrder] = sort(sourceLatitude, 'ascend');
uniqueLongitude = sourceLongitude(1:end-1);
wrappedLongitude = mod(uniqueLongitude + 180, 360) - 180;
[longitude, longitudeOrder] = sort(wrappedLongitude, 'ascend');
nLatitude = numel(latitude);
nLongitude = numel(longitude);
timeDays = timeNum - datenum(1970, 1, 1);
landUnique = land(:, 1:end-1);
landOutput = landUnique(latitudeOrder, longitudeOrder);

if ~isfile(config.outputFile)
    createOutputFile(config, nTime, nLatitude, nLongitude);
    writeCoordinatesAndMetadata(config, latitude, longitude, timeDays, ...
        landOutput);
else
    validateExistingOutput(config, nTime, nLatitude, nLongitude);
end

status = ncread(config.outputFile, 'calculation_status');
pending = find(status(:) ~= 1);
if isempty(pending)
    fprintf('All %d %s months are already complete.\n', ...
        nTime, config.componentName);
    ncwriteatt(config.outputFile, '/', 'processing_status', 'complete');
    result = outputSummary(config.outputFile);
    return;
end

[areaLongitude, areaColatitude] = size2sph(ocean);
cellArea = spheregrid(6371000, areaLongitude, areaColatitude);
oceanArea = sum(cellArea(ocean), 'omitnan');

fprintf('%s fingerprint calculation\n', config.componentName);
fprintf('Output          : %s\n', config.outputFile);
fprintf('Months          : %d total, %d pending\n', nTime, numel(pending));
fprintf('Reference period: 2003-01 through 2010-12 mean\n');
fprintf('Maximum degree  : N = %d\n\n', config.maxDegree);

runClock = tic;
for pendingPosition = 1:numel(pending)
    timePosition = pending(pendingPosition);
    monthClock = tic;
    loading = loadingSeries(:, :, timePosition) - baseline;
    loading(ocean) = 0;
    loading(~isfinite(loading)) = 0;

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
        datestr(timeNum(timePosition), 'yyyy-mm'), residualGt);
    assert(abs(oceanMeanMm - updateMm) < 1e-8, ...
        'Ocean mean and SLE update disagree for %s.', ...
        datestr(timeNum(timePosition), 'yyyy-mm'));

    fingerprintMm = fingerprintMetres(:, 1:end-1) * 1000;
    fingerprintMm = fingerprintMm(latitudeOrder, longitudeOrder);
    fingerprintMm(landOutput) = NaN;
    outputSlab = reshape(single(fingerprintMm.'), ...
        [nLongitude, nLatitude, 1]);

    ncwrite(config.outputFile, config.fingerprintVariable, outputSlab, ...
        [1, 1, timePosition]);
    ncwrite(config.outputFile, 'eustatic_equivalent', ...
        single(updateMm), timePosition);
    ncwrite(config.outputFile, 'ocean_mean_fingerprint', ...
        single(oceanMeanMm), timePosition);
    ncwrite(config.outputFile, 'input_land_mass_anomaly', ...
        inputLandMassGt, timePosition);
    ncwrite(config.outputFile, 'output_ocean_mass_response', ...
        outputOceanMassGt, timePosition);
    ncwrite(config.outputFile, 'mass_conservation_residual', ...
        residualGt, timePosition);
    ncwrite(config.outputFile, 'calculation_status', ...
        uint8(1), timePosition);

    elapsed = toc(runClock);
    meanSeconds = elapsed / pendingPosition;
    remainingMinutes = meanSeconds * ...
        (numel(pending) - pendingPosition) / 60;
    fprintf('[%3d/%3d] %s  update=%+8.4f mm  residual=%+.2e Gt  ', ...
        pendingPosition, numel(pending), ...
        datestr(timeNum(timePosition), 'yyyy-mm'), updateMm, residualGt);
    fprintf('%.2f s  ETA %.1f min\n', toc(monthClock), remainingMinutes);
end

ncwriteatt(config.outputFile, '/', 'processing_status', 'complete');
ncwriteatt(config.outputFile, '/', 'completed_utc', utcTimestamp());
result = outputSummary(config.outputFile);
fprintf('\nPASS: %d monthly %s fingerprints are complete.\n', ...
    nTime, config.componentName);
fprintf('Total elapsed time: %.2f minutes\n', toc(runClock) / 60);
fprintf('Maximum mass residual: %.3e Gt\n', result.maxMassResidualGt);
fprintf('NetCDF: %s\n', config.outputFile);
end

function timeNum = parseTime(timeRaw)
timeRaw = double(timeRaw);
if ismatrix(timeRaw) && size(timeRaw, 2) == 6
    timeNum = datenum(timeRaw);
else
    timeNum = timeRaw(:);
end
end

function createOutputFile(config, nTime, nLatitude, nLongitude)
fillSingle = single(-9999);
nccreate(config.outputFile, 'time', ...
    'Dimensions', {'time', nTime}, 'Datatype', 'double', ...
    'Format', 'netcdf4');
nccreate(config.outputFile, 'lat', ...
    'Dimensions', {'lat', nLatitude}, 'Datatype', 'double');
nccreate(config.outputFile, 'lon', ...
    'Dimensions', {'lon', nLongitude}, 'Datatype', 'double');
nccreate(config.outputFile, 'land_mask', ...
    'Dimensions', {'lon', nLongitude, 'lat', nLatitude}, ...
    'Datatype', 'uint8', 'DeflateLevel', 4, 'Shuffle', true);
nccreate(config.outputFile, config.fingerprintVariable, ...
    'Dimensions', {'lon', nLongitude, 'lat', nLatitude, 'time', nTime}, ...
    'Datatype', 'single', 'FillValue', fillSingle, ...
    'ChunkSize', [nLongitude, nLatitude, 1], ...
    'DeflateLevel', 4, 'Shuffle', true);

for name = {'eustatic_equivalent', 'ocean_mean_fingerprint'}
    nccreate(config.outputFile, name{1}, ...
        'Dimensions', {'time', nTime}, 'Datatype', 'single', ...
        'FillValue', fillSingle, 'DeflateLevel', 4, 'Shuffle', true);
end
for name = {'input_land_mass_anomaly', 'output_ocean_mass_response', ...
        'mass_conservation_residual'}
    nccreate(config.outputFile, name{1}, ...
        'Dimensions', {'time', nTime}, 'Datatype', 'double', ...
        'FillValue', -9999, 'DeflateLevel', 4, 'Shuffle', true);
end
nccreate(config.outputFile, 'calculation_status', ...
    'Dimensions', {'time', nTime}, 'Datatype', 'uint8', ...
    'FillValue', uint8(0), 'DeflateLevel', 4, 'Shuffle', true);
end

function writeCoordinatesAndMetadata(config, latitude, longitude, ...
        timeDays, landMask)
fileName = config.outputFile;
ncwrite(fileName, 'time', timeDays);
ncwrite(fileName, 'lat', latitude);
ncwrite(fileName, 'lon', longitude);
ncwrite(fileName, 'land_mask', uint8(landMask.'));
ncwriteatt(fileName, 'time', 'standard_name', 'time');
ncwriteatt(fileName, 'time', 'long_name', 'monthly observation time');
ncwriteatt(fileName, 'time', 'units', ...
    'days since 1970-01-01 00:00:00');
ncwriteatt(fileName, 'time', 'calendar', 'gregorian');
ncwriteatt(fileName, 'time', 'axis', 'T');
ncwriteatt(fileName, 'lat', 'standard_name', 'latitude');
ncwriteatt(fileName, 'lat', 'units', 'degrees_north');
ncwriteatt(fileName, 'lat', 'axis', 'Y');
ncwriteatt(fileName, 'lon', 'standard_name', 'longitude');
ncwriteatt(fileName, 'lon', 'units', 'degrees_east');
ncwriteatt(fileName, 'lon', 'axis', 'X');
ncwriteatt(fileName, 'land_mask', 'long_name', ...
    'land mask used by the SLE calculation');
ncwriteatt(fileName, 'land_mask', 'flag_values', uint8([0 1]));
ncwriteatt(fileName, 'land_mask', 'flag_meanings', 'ocean land');
ncwriteatt(fileName, config.fingerprintVariable, 'long_name', ...
    config.fingerprintLongName);
ncwriteatt(fileName, config.fingerprintVariable, 'units', 'mm');
ncwriteatt(fileName, config.fingerprintVariable, 'coordinates', ...
    'time lat lon');
ncwriteatt(fileName, config.fingerprintVariable, 'description', ...
    ['Relative sea-level anomaly on ocean grid cells. The 1-degree ', ...
    'sampling does not imply 1-degree physical resolution; the SLE ', ...
    'calculation is spectrally truncated at degree 60.']);
ncwriteatt(fileName, 'eustatic_equivalent', 'long_name', ...
    'uniform ocean-height update required by mass conservation');
ncwriteatt(fileName, 'eustatic_equivalent', 'units', 'mm');
ncwriteatt(fileName, 'ocean_mean_fingerprint', 'long_name', ...
    'area-weighted ocean mean of the sea-level fingerprint');
ncwriteatt(fileName, 'ocean_mean_fingerprint', 'units', 'mm');
ncwriteatt(fileName, 'input_land_mass_anomaly', 'long_name', ...
    'land-loading mass anomaly relative to the reference period');
ncwriteatt(fileName, 'input_land_mass_anomaly', 'units', 'Gt');
ncwriteatt(fileName, 'output_ocean_mass_response', 'long_name', ...
    'integrated ocean mass response represented by the fingerprint');
ncwriteatt(fileName, 'output_ocean_mass_response', 'units', 'Gt');
ncwriteatt(fileName, 'mass_conservation_residual', 'long_name', ...
    'input land mass anomaly plus output ocean mass response');
ncwriteatt(fileName, 'mass_conservation_residual', 'units', 'Gt');
ncwriteatt(fileName, 'calculation_status', 'long_name', ...
    'monthly calculation completion flag');
ncwriteatt(fileName, 'calculation_status', 'flag_values', uint8([0 1]));
ncwriteatt(fileName, 'calculation_status', 'flag_meanings', ...
    'pending complete');
ncwriteatt(fileName, '/', 'title', config.title);
ncwriteatt(fileName, '/', 'summary', config.summary);
ncwriteatt(fileName, '/', 'Conventions', 'CF-1.10');
ncwriteatt(fileName, '/', 'component_key', config.componentKey);
ncwriteatt(fileName, '/', 'component', config.componentName);
ncwriteatt(fileName, '/', 'source_variable', config.sourceVariable);
ncwriteatt(fileName, '/', 'source_file', config.sourceFile);
ncwriteatt(fileName, '/', 'source_loading_units', 'kg m-2 (mm EWH)');
ncwriteatt(fileName, '/', 'source_loading_type', ...
    'cumulative land mass anomaly');
ncwriteatt(fileName, '/', 'ocean_mask_file', config.maskFile);
ncwriteatt(fileName, '/', 'reference_period', ...
    '2003-01 through 2010-12 monthly mean');
ncwriteatt(fileName, '/', 'reference_period_months', int32(96));
ncwriteatt(fileName, '/', 'sle_maximum_degree', int32(config.maxDegree));
ncwriteatt(fileName, '/', 'sle_model', ...
    'elastic self-attraction and loading; fixed shoreline; no rotation');
ncwriteatt(fileName, '/', 'sle_directory', config.sleDir);
ncwriteatt(fileName, '/', 'harmonics_directory', config.harmonicsDir);
ncwriteatt(fileName, '/', 'processing_status', 'incomplete');
ncwriteatt(fileName, '/', 'created_utc', utcTimestamp());
end

function validateExistingOutput(config, nTime, nLatitude, nLongitude)
info = ncinfo(config.outputFile);
dimensionNames = string({info.Dimensions.Name});
dimensionLengths = [info.Dimensions.Length];
expectedNames = ["time", "lat", "lon"];
expectedLengths = [nTime, nLatitude, nLongitude];
for k = 1:numel(expectedNames)
    found = find(dimensionNames == expectedNames(k), 1);
    assert(~isempty(found) && dimensionLengths(found) == expectedLengths(k), ...
        'Existing output has an incompatible %s dimension.', ...
        expectedNames(k));
end
fingerprintInfo = ncinfo(config.outputFile, config.fingerprintVariable);
fingerprintDimensions = string({fingerprintInfo.Dimensions.Name});
assert(isequal(fingerprintDimensions, ["lon", "lat", "time"]), ...
    'Existing output has a nonstandard fingerprint dimension order.');
assert(double(ncreadatt(config.outputFile, '/', ...
    'sle_maximum_degree')) == config.maxDegree, ...
    'Existing output was calculated with a different SLE degree.');
assert(strcmp(ncreadatt(config.outputFile, '/', 'reference_period'), ...
    '2003-01 through 2010-12 monthly mean'), ...
    'Existing output uses a different reference period.');
assert(strcmp(ncreadatt(config.outputFile, '/', 'source_variable'), ...
    config.sourceVariable), ...
    'Existing output uses a different source variable.');
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
