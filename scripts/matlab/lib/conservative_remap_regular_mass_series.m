function [targetMassKg, diagnostics] = conservative_remap_regular_mass_series( ...
        sourceDensity, sourceLat, sourceLon, targetLat, targetLon)
%CONSERVATIVE_REMAP_REGULAR_MASS_SERIES Conservative remap for 2-D/3-D data.
% SOURCE_DENSITY is kg/m^2 on a complete regular global grid. The optional
% third dimension is time. TARGETMASSKG contains integrated kg per target
% cell, so total mass is conserved before the island policy is applied.

earthRadius = 6371000;
sourceLat = double(sourceLat(:));
sourceLon = double(sourceLon(:));
targetLat = double(targetLat(:));
targetLon = double(targetLon(:));
sourceDensity = double(sourceDensity);

assert(size(sourceDensity, 1) == numel(sourceLat) && ...
    size(sourceDensity, 2) == numel(sourceLon) && ndims(sourceDensity) <= 3, ...
    'Source density dimensions do not match its coordinates.');

[sourceLatSorted, sourceLatOrder] = sort(sourceLat, 'ascend');
[sourceLonSorted, sourceLonOrder] = sort(sourceLon, 'ascend');
[targetLatSorted, targetLatOrder] = sort(targetLat, 'ascend');
[targetLonSorted, targetLonOrder] = sort(targetLon, 'ascend');
assert(all(diff(sourceLatSorted) > 0) && all(diff(sourceLonSorted) > 0), ...
    'Source coordinates must be unique.');
assert(all(diff(targetLatSorted) > 0) && all(diff(targetLonSorted) > 0), ...
    'Target coordinates must be unique.');

sourceDensitySorted = sourceDensity(sourceLatOrder, sourceLonOrder, :);
sourceDensitySorted(~isfinite(sourceDensitySorted)) = 0;

sourceLatBounds = centreBounds(sourceLatSorted, -90, 90);
targetLatBounds = centreBounds(targetLatSorted, -90, 90);
sourceLonBounds = centreBounds(sourceLonSorted, 0, 360);
targetLonBounds = centreBounds(targetLonSorted, 0, 360);
latOverlap = latitudeOverlap(sourceLatBounds, targetLatBounds);
lonOverlap = linearOverlap(sourceLonBounds, targetLonBounds) * pi / 180;

if ismatrix(sourceDensitySorted)
    targetMassSorted = earthRadius^2 * ...
        (latOverlap * sourceDensitySorted * lonOverlap.');
else
    targetMassSorted = earthRadius^2 * pagemtimes( ...
        pagemtimes(latOverlap, sourceDensitySorted), lonOverlap.');
end
targetMassKg = zeros(numel(targetLat), numel(targetLon), ...
    size(sourceDensitySorted, 3));
targetMassKg(targetLatOrder, targetLonOrder, :) = targetMassSorted;
if ismatrix(sourceDensity)
    targetMassKg = targetMassKg(:, :, 1);
end

sourceLatFactor = diff(sind(sourceLatBounds));
sourceLonWidth = diff(sourceLonBounds) * pi / 180;
sourceAreaSorted = earthRadius^2 * ...
    (sourceLatFactor(:) * sourceLonWidth(:).');
sourceMassKg = squeeze(sum(sourceDensitySorted .* sourceAreaSorted, ...
    [1 2], 'omitnan'));
targetTotalKg = squeeze(sum(targetMassKg, [1 2], 'omitnan'));
massScaleKg = squeeze(sum(abs(sourceDensitySorted) .* sourceAreaSorted, ...
    [1 2], 'omitnan'));
massResidualKg = targetTotalKg - sourceMassKg;
toleranceKg = max(1, massScaleKg * 1e-12);
assert(all(abs(massResidualKg) <= toleranceKg), ...
    'Conservative remapping changed total mass by %.6g kg.', ...
    max(abs(massResidualKg)));

diagnostics = struct( ...
    'sourceMassKg', sourceMassKg, ...
    'targetMassKg', targetTotalKg, ...
    'massResidualKg', massResidualKg, ...
    'massScaleKg', massScaleKg);
end

function bounds = centreBounds(centres, lowerLimit, upperLimit)
bounds = zeros(numel(centres) + 1, 1);
bounds(2:end-1) = (centres(1:end-1) + centres(2:end)) / 2;
bounds(1) = lowerLimit;
bounds(end) = upperLimit;
assert(all(diff(bounds) > 0), 'Calculated cell bounds are not increasing.');
end

function overlap = latitudeOverlap(sourceBounds, targetBounds)
sourceSouth = sourceBounds(1:end-1).';
sourceNorth = sourceBounds(2:end).';
targetSouth = targetBounds(1:end-1);
targetNorth = targetBounds(2:end);
overlapSouth = max(targetSouth, sourceSouth);
overlapNorth = min(targetNorth, sourceNorth);
valid = overlapNorth > overlapSouth;
overlap = zeros(size(overlapSouth));
overlap(valid) = sind(overlapNorth(valid)) - sind(overlapSouth(valid));
end

function overlap = linearOverlap(sourceBounds, targetBounds)
sourceWest = sourceBounds(1:end-1).';
sourceEast = sourceBounds(2:end).';
targetWest = targetBounds(1:end-1);
targetEast = targetBounds(2:end);
overlap = max(0, min(targetEast, sourceEast) - ...
    max(targetWest, sourceWest));
end
