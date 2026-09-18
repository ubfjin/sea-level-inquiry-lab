function policy = build_island_mass_transfer( ...
        land, latitude, longitude, maxDistanceKm)
%BUILD_ISLAND_MASS_TRANSFER Build one reusable nearest-land transfer map.
% Land cells retain their mass. Ocean cells whose centres are no farther
% than MAXDISTANCEKM from a land-cell centre transfer all mass to the
% nearest land cell. More distant ocean-cell mass is discarded and can be
% diagnosed with POLICY.farOceanIndex.

arguments
    land (:,:) logical
    latitude (:,1) double
    longitude (:,1) double
    maxDistanceKm (1,1) double {mustBePositive} = 250
end

assert(isequal(size(land), [numel(latitude), numel(longitude)]), ...
    'Mask dimensions do not match latitude and longitude.');

earthRadiusKm = 6371;
[latGrid, lonGrid] = ndgrid(latitude, longitude);
landIndex = find(land);
oceanIndex = find(~land);
landXyz = unitSphere(latGrid(landIndex), lonGrid(landIndex));

nearestLandIndex = zeros(numel(oceanIndex), 1);
nearestDistanceKm = inf(numel(oceanIndex), 1);
chunkSize = 500;
for first = 1:chunkSize:numel(oceanIndex)
    last = min(first + chunkSize - 1, numel(oceanIndex));
    rows = first:last;
    oceanXyz = unitSphere(latGrid(oceanIndex(rows)), ...
        lonGrid(oceanIndex(rows)));
    [nearestCosine, nearestColumn] = max(oceanXyz * landXyz.', [], 2);
    nearestCosine = min(1, max(-1, nearestCosine));
    nearestDistanceKm(rows) = acos(nearestCosine) * earthRadiusKm;
    nearestLandIndex(rows) = landIndex(nearestColumn);
end

eligible = nearestDistanceKm <= maxDistanceKm;
eligibleOceanIndex = oceanIndex(eligible);
farOceanIndex = oceanIndex(~eligible);
nCell = numel(land);
sourceIndex = [landIndex; eligibleOceanIndex];
destinationIndex = [landIndex; nearestLandIndex(eligible)];
transfer = sparse(destinationIndex, sourceIndex, 1, nCell, nCell);

policy = struct( ...
    'transfer', transfer, ...
    'landIndex', landIndex, ...
    'oceanIndex', oceanIndex, ...
    'eligibleOceanIndex', eligibleOceanIndex, ...
    'farOceanIndex', farOceanIndex, ...
    'eligibleDistanceKm', nearestDistanceKm(eligible), ...
    'maxDistanceKm', maxDistanceKm);
end

function xyz = unitSphere(latitude, longitude)
xyz = [cosd(latitude) .* cosd(longitude), ...
    cosd(latitude) .* sind(longitude), sind(latitude)];
end
