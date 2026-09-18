%% Compare small-island mass treatments before full component processing
% Policies:
%   1. Delete all target-ocean loading after conservative remapping.
%   2. Move loading to the nearest land cell when it is within 250 km.
%   3. Distribute loading among up to four land cells within 250 km.
%
% SLE always receives the original 181 x 361 ocean mask. This script does
% not modify any source file or production fingerprint file.

clearvars;
clc;

scriptDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(scriptDir));
sourceDir = fullfile(projectRoot, 'data', 'source', 'barystatic');
outputDir = fullfile(projectRoot, 'outputs', 'barystatic');
addpath(fullfile(scriptDir, 'lib'), '-begin');
addpath('D:\GRACE_edu\Archive\Simons', '-begin');
addpath('D:\GRACE_edu\Archive\Jeon', '-begin');
assert(strcmp(which('SLE'), 'D:\GRACE_edu\Archive\Jeon\SLE.m'), ...
    'The pinned SLE.m is not first on the MATLAB path.');

maskData = load(fullfile(sourceDir, 'ocean_mask', ...
    'landmask_181361.mat'), 'land');
land = logical(maskData.land);
ocean = ~land;
[targetLon, targetColat] = size2sph(ocean);
targetLat = 90 - targetColat(:);
targetLon = targetLon(:);
targetArea = spheregrid(6371000, targetLon, targetColat);

%% Groundwater: 2010-12 anomaly from the 2003-2010 monthly mean
fprintf('\nPreparing Groundwater 2010-12 anomaly...\n');
groundwaterFile = fullfile(sourceDir, ...
    'Groundwater_Wada_1960-2010.mat');
groundwaterData = load(groundwaterFile, ...
    'groundwater', 'lat_origin', 'lon_origin', 'time');
groundwaterTime = datenum(groundwaterData.time);
groundwaterDate = datevec(groundwaterTime);
groundwaterReference = groundwaterDate(:, 1) >= 2003 & ...
    groundwaterDate(:, 1) <= 2010;
assert(nnz(groundwaterReference) == 96, ...
    'Groundwater reference period must contain 96 months.');
groundwaterTarget = find(groundwaterDate(:, 1) == 2010 & ...
    groundwaterDate(:, 2) == 12, 1);
assert(~isempty(groundwaterTarget), ...
    'Groundwater 2010-12 field was not found.');
groundwaterAnomaly = ...
    double(groundwaterData.groundwater(:, :, groundwaterTarget)) - ...
    mean(double(groundwaterData.groundwater(:, :, ...
    groundwaterReference)), 3, 'omitnan');

[groundwaterMass, groundwaterRemap] = ...
    conservative_remap_regular_mass(groundwaterAnomaly, ...
    groundwaterData.lat_origin, groundwaterData.lon_origin, ...
    targetLat, targetLon);
clear groundwaterData groundwaterAnomaly;

[groundwaterRows, groundwaterMetrics] = comparePolicies( ...
    "Groundwater", "2010-12", groundwaterMass, ...
    groundwaterRemap, land, ocean, targetLat, targetLon, targetArea);

%% DAM: 2017-12 anomaly after monthly interpolation from December values
fprintf('\nPreparing DAM 2017-12 anomaly...\n');
damFile = fullfile(sourceDir, 'DAM.mat');
damData = load(damFile, 'dam_grid', 'yr_dam');
annualTime = datenum(damData.yr_dam(:), 12, 15);
referenceTime = datenum(repelem((2003:2010).', 12), ...
    repmat((1:12).', 8, 1), 15);
damReference = zeros(size(damData.dam_grid, 1), ...
    size(damData.dam_grid, 2));
for k = 1:numel(referenceTime)
    right = find(annualTime >= referenceTime(k), 1, 'first');
    left = find(annualTime <= referenceTime(k), 1, 'last');
    if left == right
        monthlyField = double(damData.dam_grid(:, :, left));
    else
        fraction = (referenceTime(k) - annualTime(left)) / ...
            (annualTime(right) - annualTime(left));
        monthlyField = ...
            (1 - fraction) * double(damData.dam_grid(:, :, left)) + ...
            fraction * double(damData.dam_grid(:, :, right));
    end
    damReference = damReference + monthlyField;
end
damReference = damReference / numel(referenceTime);
damAnomaly = double(damData.dam_grid(:, :, end)) - damReference;
damLat = (89.5:-1:-89.5).';
damLon = (0.5:1:359.5).';

[damMass, damRemap] = conservative_remap_regular_mass( ...
    damAnomaly, damLat, damLon, targetLat, targetLon);
clear damData damAnomaly damReference monthlyField;

[damRows, damMetrics] = comparePolicies( ...
    "DAM", "2017-12", damMass, damRemap, ...
    land, ocean, targetLat, targetLon, targetArea);

%% Save the compact numerical comparison
comparison = [groundwaterRows; damRows];
if ~isfolder(outputDir)
    mkdir(outputDir);
end
outputCsv = fullfile(outputDir, 'island_mass_policy_comparison.csv');
writetable(comparison, outputCsv);

fprintf('\nPolicy comparison\n');
disp(comparison(:, {'component', 'policy', 'sourceMassGt', ...
    'appliedMassGt', 'omittedMassGt', 'omittedPercent', 'updateMm'}));
printMetrics(groundwaterMetrics);
printMetrics(damMetrics);
fprintf('\nCSV: %s\n', outputCsv);

function [rows, metrics] = comparePolicies(component, targetDate, ...
        targetMass, remapDiagnostics, land, ocean, lat, lon, cellArea)
maxDistanceKm = 250;
earthRadiusKm = 6371;
minimumMassKg = 1;

deletedMass = targetMass;
deletedMass(ocean) = 0;

[latGrid, lonGrid] = ndgrid(lat, lon);
landIndex = find(land);
oceanLoadingIndex = find(ocean & abs(targetMass) >= minimumMassKg);
landXyz = unitSphere(latGrid(landIndex), lonGrid(landIndex));
sourceXyz = unitSphere(latGrid(oceanLoadingIndex), ...
    lonGrid(oceanLoadingIndex));

cosineDistance = sourceXyz * landXyz.';
[nearestCosine, nearestColumn] = maxk(cosineDistance, 4, 2);
nearestCosine = min(1, max(-1, nearestCosine));
distanceKm = acos(nearestCosine) * earthRadiusKm;
eligible = distanceKm(:, 1) <= maxDistanceKm;
sourceMass = targetMass(oceanLoadingIndex);

nearestMass = deletedMass;
for k = find(eligible).'
    destination = landIndex(nearestColumn(k, 1));
    nearestMass(destination) = nearestMass(destination) + sourceMass(k);
end

weightedMass = deletedMass;
for k = find(eligible).'
    validNeighbour = distanceKm(k, :) <= maxDistanceKm;
    destinations = landIndex(nearestColumn(k, validNeighbour));
    weights = 1 ./ max(distanceKm(k, validNeighbour), 1e-6);
    weights = weights / sum(weights);
    weightedMass(destinations) = weightedMass(destinations) + ...
        sourceMass(k) * weights.';
end

assert(abs(sum(nearestMass, 'all') - sum(weightedMass, 'all')) < 1, ...
    'Nearest and weighted policies must retain the same total mass.');

policyNames = ["delete", "nearest_land_250km", ...
    "four_land_cells_250km"];
policyMass = {deletedMass, nearestMass, weightedMass};
fingerprints = cell(1, 3);
updatesMm = zeros(1, 3);
sourceMassGt = remapDiagnostics.sourceMassKg / 1e12;
rows = table('Size', [3 8], ...
    'VariableTypes', {'string', 'string', 'string', 'double', ...
    'double', 'double', 'double', 'double'}, ...
    'VariableNames', {'component', 'targetDate', 'policy', ...
    'sourceMassGt', 'appliedMassGt', 'omittedMassGt', ...
    'omittedPercent', 'updateMm'});

for policy = 1:3
    loading = policyMass{policy} ./ cellArea;
    loading(~isfinite(loading)) = 0;
    [fingerprints{policy}, update] = SLE( ...
        ocean, 0, loading, 60);
    updatesMm(policy) = update * 1000;
    appliedMassGt = sum(policyMass{policy}, 'all') / 1e12;
    omittedMassGt = sourceMassGt - appliedMassGt;
    rows(policy, :) = {component, targetDate, policyNames(policy), ...
        sourceMassGt, appliedMassGt, omittedMassGt, ...
        abs(omittedMassGt / sourceMassGt) * 100, updatesMm(policy)};
end

oceanArea = sum(cellArea(ocean), 'omitnan');
deleteNearestDifference = ...
    (fingerprints{1} - fingerprints{2}) * 1000;
nearestWeightedDifference = ...
    (fingerprints{2} - fingerprints{3}) * 1000;

eligibleMass = abs(sourceMass(eligible));
eligibleDistance = distanceKm(eligible, 1);
farMassKg = sum(sourceMass(~eligible), 'omitnan');
relocatedMassKg = sum(sourceMass(eligible), 'omitnan');
relocatedAbsoluteMassKg = sum(eligibleMass, 'omitnan');

metrics = struct( ...
    'component', component, ...
    'targetDate', targetDate, ...
    'oceanCandidateCells', numel(oceanLoadingIndex), ...
    'relocatedCells', nnz(eligible), ...
    'farCells', nnz(~eligible), ...
    'relocatedMassGt', relocatedMassKg / 1e12, ...
    'relocatedAbsoluteMassGt', relocatedAbsoluteMassKg / 1e12, ...
    'farMassGt', farMassKg / 1e12, ...
    'distanceMedianKm', weightedQuantile(eligibleDistance, ...
        eligibleMass, 0.50), ...
    'distanceP95Km', weightedQuantile(eligibleDistance, ...
        eligibleMass, 0.95), ...
    'distanceMaximumKm', max(eligibleDistance, [], 'omitnan'), ...
    'deleteNearestRmsMm', areaRms(deleteNearestDifference, ...
        ocean, cellArea, oceanArea), ...
    'deleteNearestMaxMm', max(abs(deleteNearestDifference(ocean)), ...
        [], 'omitnan'), ...
    'nearestWeightedRmsMm', areaRms(nearestWeightedDifference, ...
        ocean, cellArea, oceanArea), ...
    'nearestWeightedMaxMm', ...
        max(abs(nearestWeightedDifference(ocean)), [], 'omitnan'), ...
    'nearestWeightedUpdateDifferenceMm', ...
        updatesMm(2) - updatesMm(3));
end

function xyz = unitSphere(latitude, longitude)
xyz = [cosd(latitude) .* cosd(longitude), ...
    cosd(latitude) .* sind(longitude), sind(latitude)];
end

function value = weightedQuantile(values, weights, probability)
if isempty(values)
    value = NaN;
    return;
end
[values, order] = sort(values);
weights = weights(order);
cumulative = cumsum(weights) / sum(weights);
value = values(find(cumulative >= probability, 1, 'first'));
end

function value = areaRms(field, ocean, cellArea, oceanArea)
value = sqrt(sum(field(ocean).^2 .* cellArea(ocean), ...
    'omitnan') / oceanArea);
end

function printMetrics(metrics)
fprintf('\n%s (%s) spatial sensitivity\n', ...
    metrics.component, metrics.targetDate);
fprintf('Ocean-mask loading cells: %d; relocated: %d; beyond 250 km: %d\n', ...
    metrics.oceanCandidateCells, metrics.relocatedCells, metrics.farCells);
fprintf('Relocated mass: %+.4f Gt (absolute %.4f Gt); far mass: %+.4f Gt\n', ...
    metrics.relocatedMassGt, metrics.relocatedAbsoluteMassGt, ...
    metrics.farMassGt);
fprintf('Nearest-land distance (mass weighted): median %.1f km, ', ...
    metrics.distanceMedianKm);
fprintf('p95 %.1f km, maximum %.1f km\n', ...
    metrics.distanceP95Km, metrics.distanceMaximumKm);
fprintf('Delete vs nearest: RMS %.6f mm, max %.6f mm\n', ...
    metrics.deleteNearestRmsMm, metrics.deleteNearestMaxMm);
fprintf('Nearest vs four-cell: RMS %.6f mm, max %.6f mm, ', ...
    metrics.nearestWeightedRmsMm, metrics.nearestWeightedMaxMm);
fprintf('mean update difference %+.3e mm\n', ...
    metrics.nearestWeightedUpdateDifferenceMm);
end
