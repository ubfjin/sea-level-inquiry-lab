%% Convert the completed GRACE fingerprint field to the web NetCDF format
% FMSAL already contains the forward-modelled relative sea-level fingerprint
% over the ocean. No SLE calculation is repeated here.
clearvars;
clc;

scriptDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(scriptDir));
sourceDir = fullfile(projectRoot, 'data', 'source', 'barystatic');
outputDir = fullfile(projectRoot, 'data', 'processed', 'barystatic');

sourceFile = fullfile(sourceDir, ...
    'JJ2_CSR_RL06_GSM_FM_EWH_d1=X_c20=X_c21=X_s21=X_PGR=PE18_200301_202305.mat');
maskFile = fullfile(sourceDir, 'ocean_mask', 'landmask_181361.mat');
outputFile = fullfile(outputDir, ...
    'grace_ocean_mass_fingerprint_1deg_monthly_200301_202304.nc');

assert(isfile(sourceFile), 'GRACE source file is missing.');
assert(isfile(maskFile), 'Land-mask file is missing.');
if ~isfolder(outputDir)
    mkdir(outputDir);
end
if isfile(outputFile)
    delete(outputFile);
end

fprintf('Loading completed GRACE fingerprint field...\n');
source = load(sourceFile, 'FMSAL');
mask = load(maskFile, 'land');
assert(isfield(source, 'FMSAL'), 'FMSAL was not found.');
assert(isfield(mask, 'land'), 'land was not found.');

fingerprint = double(source.FMSAL);
land = logical(mask.land);
ocean = ~land;
assert(isequal(size(fingerprint), [181 361 232]), ...
    'Expected FMSAL to be 181 x 361 x 232.');
assert(isequal(size(land), [181 361]), ...
    'Expected land mask to be 181 x 361.');

sourceTime = datenum(2003, ...
    [1:14 * 12 + 5, 15 * 12 + 6:21 * 12 - 8], 15);
sourceTime = sourceTime(:);
assert(numel(sourceTime) == size(fingerprint, 3), ...
    'GRACE time axis does not match FMSAL.');
assert(strcmp(datestr(sourceTime(1), 'yyyy-mm'), '2003-01') && ...
    strcmp(datestr(sourceTime(end), 'yyyy-mm'), '2023-04'), ...
    'Unexpected GRACE date range.');

sourceDate = datevec(sourceTime);
sourceMonthIndex = sourceDate(:, 1) * 12 + sourceDate(:, 2);
monthSteps = diff(sourceMonthIndex);
assert(nnz(monthSteps ~= 1) == 1 && monthSteps(monthSteps ~= 1) == 13, ...
    'Expected one 12-month GRACE/GRACE-FO mission gap.');
gapPosition = find(monthSteps ~= 1, 1);
assert(strcmp(datestr(sourceTime(gapPosition), 'yyyy-mm'), '2017-05') && ...
    strcmp(datestr(sourceTime(gapPosition + 1), 'yyyy-mm'), '2018-06'), ...
    'Unexpected GRACE mission-gap dates.');

fullTime = datenum(2003, 1:(20 * 12 + 4), 15).';
fullDate = datevec(fullTime);
fullMonthIndex = fullDate(:, 1) * 12 + fullDate(:, 2);
[available, fullPosition] = ismember(fullMonthIndex, sourceMonthIndex);
assert(nnz(available) == 232 && nnz(~available) == 12, ...
    'Expected 232 source months and 12 unfilled gap months.');
sourcePosition = zeros(numel(fullTime), 1);
sourcePosition(available) = fullPosition(available);

baselineIndex = sourceTime >= datenum(2003, 1, 1) & ...
    sourceTime <= datenum(2010, 12, 31);
assert(nnz(baselineIndex) == 96, ...
    'Expected 96 months in the 2003-2010 reference period.');
baseline = mean(fingerprint(:, :, baselineIndex), 3, 'omitnan');

sourceLatitude = (90:-1:-90).';
sourceLongitude = (0:360).';
[latitude, latitudeOrder] = sort(sourceLatitude, 'ascend');
uniqueLongitude = sourceLongitude(1:end-1);
wrappedLongitude = mod(uniqueLongitude + 180, 360) - 180;
[longitude, longitudeOrder] = sort(wrappedLongitude, 'ascend');
landUnique = land(:, 1:end-1);
landOutput = landUnique(latitudeOrder, longitudeOrder);

northEdge = min(90, sourceLatitude + 0.5);
southEdge = max(-90, sourceLatitude - 0.5);
earthRadius = 6371000;
bandArea = earthRadius ^ 2 * deg2rad(1) .* ...
    (sind(northEdge) - sind(southEdge));
cellArea = repmat(bandArea, 1, 360);
oceanUnique = ocean(:, 1:end-1);
oceanArea = sum(cellArea(oceanUnique), 'omitnan');

nTime = numel(fullTime);
nLatitude = numel(latitude);
nLongitude = numel(longitude);
fillSingle = single(-9999);

nccreate(outputFile, 'time', 'Dimensions', {'time', nTime}, ...
    'Datatype', 'double', 'Format', 'netcdf4');
nccreate(outputFile, 'lat', 'Dimensions', {'lat', nLatitude}, ...
    'Datatype', 'double');
nccreate(outputFile, 'lon', 'Dimensions', {'lon', nLongitude}, ...
    'Datatype', 'double');
nccreate(outputFile, 'land_mask', ...
    'Dimensions', {'lon', nLongitude, 'lat', nLatitude}, ...
    'Datatype', 'uint8', 'DeflateLevel', 4, 'Shuffle', true);
nccreate(outputFile, 'grace_fingerprint', ...
    'Dimensions', {'lon', nLongitude, 'lat', nLatitude, 'time', nTime}, ...
    'Datatype', 'single', 'FillValue', fillSingle, ...
    'ChunkSize', [nLongitude, nLatitude, 1], ...
    'DeflateLevel', 4, 'Shuffle', true);
nccreate(outputFile, 'ocean_mean_fingerprint', ...
    'Dimensions', {'time', nTime}, 'Datatype', 'single', ...
    'FillValue', fillSingle, 'DeflateLevel', 4, 'Shuffle', true);
nccreate(outputFile, 'source_available', ...
    'Dimensions', {'time', nTime}, 'Datatype', 'uint8', ...
    'FillValue', uint8(255), 'DeflateLevel', 4, 'Shuffle', true);

ncwrite(outputFile, 'time', fullTime - datenum(1970, 1, 1));
ncwrite(outputFile, 'lat', latitude);
ncwrite(outputFile, 'lon', longitude);
ncwrite(outputFile, 'land_mask', uint8(landOutput.'));
ncwrite(outputFile, 'source_available', uint8(available));

ncwriteatt(outputFile, 'time', 'standard_name', 'time');
ncwriteatt(outputFile, 'time', 'long_name', 'monthly observation time');
ncwriteatt(outputFile, 'time', 'units', 'days since 1970-01-01 00:00:00');
ncwriteatt(outputFile, 'time', 'calendar', 'gregorian');
ncwriteatt(outputFile, 'time', 'axis', 'T');
ncwriteatt(outputFile, 'lat', 'standard_name', 'latitude');
ncwriteatt(outputFile, 'lat', 'units', 'degrees_north');
ncwriteatt(outputFile, 'lat', 'axis', 'Y');
ncwriteatt(outputFile, 'lon', 'standard_name', 'longitude');
ncwriteatt(outputFile, 'lon', 'units', 'degrees_east');
ncwriteatt(outputFile, 'lon', 'axis', 'X');
ncwriteatt(outputFile, 'land_mask', 'long_name', ...
    'land mask used to expose only ocean fingerprint values');
ncwriteatt(outputFile, 'land_mask', 'flag_values', uint8([0 1]));
ncwriteatt(outputFile, 'land_mask', 'flag_meanings', 'ocean land');
ncwriteatt(outputFile, 'grace_fingerprint', 'long_name', ...
    'GRACE and GRACE-FO relative sea-level fingerprint anomaly');
ncwriteatt(outputFile, 'grace_fingerprint', 'units', 'mm');
ncwriteatt(outputFile, 'grace_fingerprint', 'coordinates', 'time lat lon');
ncwriteatt(outputFile, 'grace_fingerprint', 'description', ...
    ['Ocean values from the completed forward-modelled FMSAL field. ', ...
    'Land source-loading values are masked in this web product.']);
ncwriteatt(outputFile, 'ocean_mean_fingerprint', 'long_name', ...
    'area-weighted global ocean mean of the GRACE fingerprint');
ncwriteatt(outputFile, 'ocean_mean_fingerprint', 'units', 'mm');
ncwriteatt(outputFile, 'source_available', 'long_name', ...
    'GRACE or GRACE-FO monthly source availability');
ncwriteatt(outputFile, 'source_available', 'flag_values', uint8([0 1]));
ncwriteatt(outputFile, 'source_available', 'flag_meanings', ...
    'mission_gap source_available');

fprintf('Writing %d source months; leaving 12 mission-gap months empty...\n', ...
    nnz(available));
for fullIndex = 1:nTime
    if ~available(fullIndex)
        continue;
    end
    sourceIndex = sourcePosition(fullIndex);
    field = fingerprint(:, :, sourceIndex) - baseline;
    oceanField = field(:, 1:end-1);
    oceanMean = sum(oceanField(oceanUnique) .* cellArea(oceanUnique), ...
        'omitnan') / oceanArea;
    outputField = oceanField(latitudeOrder, longitudeOrder);
    outputField(landOutput) = NaN;
    outputSlab = reshape(single(outputField.'), ...
        [nLongitude, nLatitude, 1]);
    ncwrite(outputFile, 'grace_fingerprint', outputSlab, ...
        [1, 1, fullIndex]);
    ncwrite(outputFile, 'ocean_mean_fingerprint', ...
        single(oceanMean), fullIndex);
end

ncwriteatt(outputFile, '/', 'title', ...
    'Monthly GRACE and GRACE-FO ocean-mass sea-level fingerprints');
ncwriteatt(outputFile, '/', 'summary', ...
    ['Web-ready ocean fingerprint fields converted from the completed ', ...
    'FMSAL forward-model result; no SLE calculation was repeated.']);
ncwriteatt(outputFile, '/', 'Conventions', 'CF-1.10');
ncwriteatt(outputFile, '/', 'component_key', 'grace_ocean_mass');
ncwriteatt(outputFile, '/', 'source_variable', 'FMSAL');
ncwriteatt(outputFile, '/', 'source_file', sourceFile);
ncwriteatt(outputFile, '/', 'source_units', 'kg m-2 on land; mm relative sea level over ocean');
ncwriteatt(outputFile, '/', 'reference_period', ...
    '2003-01 through 2010-12 monthly mean removed per grid cell');
ncwriteatt(outputFile, '/', 'reference_period_months', int32(96));
ncwriteatt(outputFile, '/', 'mission_gap', ...
    '2017-06 through 2018-05 retained as missing; no interpolation');
ncwriteatt(outputFile, '/', 'web_longitude_convention', ...
    '-180 to 179 degrees; 360-degree duplicate removed');
ncwriteatt(outputFile, '/', 'positive_direction', ...
    'positive values indicate relative sea-level rise');
ncwriteatt(outputFile, '/', 'processing_status', 'complete');
ncwriteatt(outputFile, '/', 'created_utc', ...
    char(datetime('now', 'TimeZone', 'UTC', ...
    'Format', 'yyyy-MM-dd''T''HH:mm:ss''Z''')));

info = ncinfo(outputFile);
assert(info.Dimensions(1).Length == nTime || ...
    any(strcmp({info.Dimensions.Name}, 'time')), ...
    'Output time dimension was not created.');
writtenAvailable = ncread(outputFile, 'source_available');
writtenMean = ncread(outputFile, 'ocean_mean_fingerprint');
assert(nnz(writtenAvailable == 1) == 232, ...
    'Output availability flag is incomplete.');
assert(nnz(isfinite(writtenMean) & writtenMean ~= -9999) == 232, ...
    'Output ocean-mean series is incomplete.');

fprintf('PASS: GRACE web NetCDF created.\n');
fprintf('Output: %s\n', outputFile);
fprintf('Available months: %d; mission-gap months: %d\n', ...
    nnz(writtenAvailable == 1), nnz(writtenAvailable == 0));
