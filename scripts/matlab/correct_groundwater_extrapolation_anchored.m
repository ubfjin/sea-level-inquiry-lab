%% Anchor Groundwater extrapolation to the observed 2010-12 grid
% The 1991-2010 per-cell slope is retained, but the future projection starts
% from the actual 2010-12 field so there is no regression-intercept jump.

clearvars;
clc;

scriptDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(scriptDir));
preparedFile = fullfile(projectRoot, 'data', 'processed', 'barystatic', ...
    'source_loading', ...
    'groundwater_loading_1deg_monthly_196001_202304.nc');
fingerprintFile = fullfile(projectRoot, 'data', 'processed', 'barystatic', ...
    'groundwater_fingerprint_1deg_monthly_199301_202304.nc');

timeNum = double(ncread(preparedFile, 'time')) + datenum(1970, 1, 1);
referenceIndex = find(timeNum >= datenum(1991, 1, 1) & ...
    timeNum <= datenum(2010, 12, 31));
futureIndex = find(timeNum >= datenum(2011, 1, 1));
assert(numel(referenceIndex) == 240 && numel(futureIndex) == 148);
assert(referenceIndex(end) + 1 == futureIndex(1));

latitude = ncread(preparedFile, 'lat');
longitude = ncread(preparedFile, 'lon');
referenceLoading = double(ncread(preparedFile, 'loading', ...
    [1 1 referenceIndex(1)], ...
    [numel(latitude) numel(longitude) numel(referenceIndex)]));
referenceLoading = reshape(referenceLoading, [], numel(referenceIndex));
futureLoading = anchoredProjection(referenceLoading, ...
    referenceIndex, futureIndex);
clear referenceLoading;

diagnosticNames = {'source_mass', 'applied_land_mass', ...
    'relocated_island_mass', 'discarded_far_mass'};
futureDiagnostics = struct();
for k = 1:numel(diagnosticNames)
    name = diagnosticNames{k};
    values = double(ncread(preparedFile, name));
    futureDiagnostics.(name) = anchoredProjection( ...
        values(referenceIndex).', referenceIndex, futureIndex).';
end

chunkMonths = 24;
for first = 1:chunkMonths:numel(futureIndex)
    last = min(first + chunkMonths - 1, numel(futureIndex));
    local = first:last;
    target = futureIndex(local);
    loading = reshape(futureLoading(:, local), ...
        [numel(latitude) numel(longitude) numel(local)]);
    ncwrite(preparedFile, 'loading', single(loading), [1 1 target(1)]);
    for k = 1:numel(diagnosticNames)
        name = diagnosticNames{k};
        ncwrite(preparedFile, name, futureDiagnostics.(name)(local), target(1));
    end
    residual = futureDiagnostics.source_mass(local) - ...
        futureDiagnostics.applied_land_mass(local) - ...
        futureDiagnostics.discarded_far_mass(local);
    ncwrite(preparedFile, 'mass_accounting_residual', residual, target(1));
    ncwrite(preparedFile, 'preparation_status', ...
        ones(numel(local), 1, 'uint8'), target(1));
end
ncwriteatt(preparedFile, '/', 'extrapolation_method', ...
    ['1991-2010 per-grid-cell linear slope anchored to the observed ', ...
    '2010-12 grid; first extrapolated month is 2010-12 plus one slope step']);
ncwriteatt(preparedFile, '/', 'extrapolation_anchor', '2010-12 observed grid');
ncwriteatt(preparedFile, '/', 'completed_utc', utcTimestamp());

if isfile(fingerprintFile)
    outputTime = double(ncread(fingerprintFile, 'time')) + datenum(1970, 1, 1);
    resetIndex = find(outputTime >= datenum(2011, 1, 1));
    ncwrite(fingerprintFile, 'calculation_status', ...
        zeros(numel(resetIndex), 1, 'uint8'), resetIndex(1));
    ncwriteatt(fingerprintFile, '/', 'processing_status', 'incomplete');
    ncwriteatt(fingerprintFile, '/', 'groundwater_extrapolation_method', ...
        ['1991-2010 per-grid-cell linear slope anchored to the observed ', ...
        '2010-12 grid']);
end

fprintf(['PASS: corrected %d Groundwater extrapolation months and reset ', ...
    'the 2011+ fingerprint status.\n'], numel(futureIndex));

function projected = anchoredProjection(reference, referenceIndex, targetIndex)
reference = double(reference);
x = double(referenceIndex(:));
xc = x - mean(x);
slope = reference * xc / sum(xc .^ 2);
stepsAfterAnchor = double(targetIndex(:)).' - referenceIndex(end);
projected = reference(:, end) + slope * stepsAfterAnchor;
end

function value = utcTimestamp()
value = char(datetime('now', 'TimeZone', 'UTC', ...
    'Format', 'yyyy-MM-dd''T''HH:mm:ss''Z'''));
end
