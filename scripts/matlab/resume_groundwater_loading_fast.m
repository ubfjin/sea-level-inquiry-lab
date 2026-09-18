%% Efficiently resume Groundwater preparation from a pre-v7.3 MAT file
% MATLAB cannot partially read this compressed legacy MAT file. Load the
% 1.27 GB source array once, then process it in time chunks in memory.

clearvars;
clc;

scriptDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(scriptDir));
sourceDir = fullfile(projectRoot, 'data', 'source', 'barystatic');
preparedDir = fullfile(projectRoot, 'data', 'processed', ...
    'barystatic', 'source_loading');
addpath(fullfile(scriptDir, 'lib'), '-begin');

sourceFile = fullfile(sourceDir, 'Groundwater_Wada_1960-2010.mat');
outputFile = fullfile(preparedDir, ...
    'groundwater_loading_1deg_monthly_196001_202304.nc');
policyFile = fullfile(preparedDir, 'island_transfer_250km.mat');
assert(isfile(outputFile) && isfile(policyFile), ...
    'Run prepare_land_water_loadings once to initialize the outputs.');

maskData = load(fullfile(sourceDir, 'ocean_mask', ...
    'landmask_181361.mat'), 'land');
land = logical(maskData.land);
ocean = ~land;
[targetLon, targetColat] = size2sph(ocean);
targetLat = 90 - targetColat(:);
targetLon = targetLon(:);
targetArea = spheregrid(6371000, targetLon, targetColat);
cached = load(policyFile, 'policy');
policy = cached.policy;
coords = load(sourceFile, 'lat_origin', 'lon_origin', 'time');
rawTime = datenum(coords.time);
allTime = double(ncread(outputFile, 'time')) + datenum(1970, 1, 1);
status = ncread(outputFile, 'preparation_status');

fprintf('Loading the legacy Groundwater array once (about 1.27 GB)...\n');
source = load(sourceFile, 'groundwater');
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
        density, coords.lat_origin, coords.lon_origin, targetLat, targetLon);
    [landMass, island] = apply_island_mass_policy(targetMass, policy);
    loading = landMass ./ targetArea;
    writeChunk(outputFile, first, loading, remap.sourceMassKg, island);
    status(index) = 1;
end
clear source;

status = ncread(outputFile, 'preparation_status');
assert(all(status(1:numel(rawTime)) == 1));
futureIndex = (numel(rawTime) + 1):numel(allTime);
if any(status(futureIndex) ~= 1)
    referenceIndex = find(allTime >= datenum(1991, 1, 1) & ...
        allTime <= datenum(2010, 12, 31));
    referenceLoading = double(ncread(outputFile, 'loading', ...
        [1 1 referenceIndex(1)], ...
        [numel(targetLat) numel(targetLon) numel(referenceIndex)]));
    referenceLoading = reshape(referenceLoading, [], numel(referenceIndex));
    futureLoading = project(referenceLoading, referenceIndex, futureIndex);
    clear referenceLoading;

    names = {'source_mass', 'applied_land_mass', ...
        'relocated_island_mass', 'discarded_far_mass'};
    future = struct();
    for k = 1:numel(names)
        values = double(ncread(outputFile, names{k}));
        future.(names{k}) = project(values(referenceIndex).', ...
            referenceIndex, futureIndex).';
    end
    for first = 1:chunkMonths:numel(futureIndex)
        last = min(first + chunkMonths - 1, numel(futureIndex));
        local = first:last;
        index = futureIndex(local);
        if all(status(index) == 1)
            continue;
        end
        loading = reshape(futureLoading(:, local), ...
            [numel(targetLat) numel(targetLon) numel(local)]);
        island = struct( ...
            'appliedMassKg', future.applied_land_mass(local) * 1e12, ...
            'relocatedMassKg', future.relocated_island_mass(local) * 1e12, ...
            'discardedMassKg', future.discarded_far_mass(local) * 1e12, ...
            'accountingResidualKg', zeros(numel(local), 1));
        writeChunk(outputFile, index(1), loading, ...
            future.source_mass(local) * 1e12, island);
        status(index) = 1;
    end
end
ncwriteatt(outputFile, '/', 'processing_status', 'complete');
fprintf('PASS: Groundwater prepared through %s.\n', ...
    datestr(allTime(end), 'yyyy-mm'));

function writeChunk(fileName, first, loading, sourceMassKg, island)
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

function projected = project(reference, referenceIndex, targetIndex)
reference = double(reference);
x = double(referenceIndex(:));
xc = x - mean(x);
slope = reference * xc / sum(xc .^ 2);
projected = mean(reference, 2, 'omitnan') + ...
    slope * (double(targetIndex(:)).' - mean(x));
end
