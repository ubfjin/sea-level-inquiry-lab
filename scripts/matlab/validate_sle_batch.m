%% Validate monthly SLE batch processing with three Antarctic snapshots
% This script intentionally does not modify or export any source data.
% It compares the established serial calculation with a month-parallel
% calculation while preserving each month's full spatial loading pattern.

clearvars;
clc;

scriptDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(scriptDir));
barystaticDir = fullfile(projectRoot, 'data', 'source', 'barystatic');

% Pin the exact MATLAB implementation used in the one-month validation.
sleDir = 'D:\GRACE_edu\Archive\Jeon';
harmonicsDir = 'D:\GRACE_edu\Archive\Simons';

requiredFiles = {
    fullfile(sleDir, 'SLE.m')
    fullfile(harmonicsDir, 'xyz2plm.m')
    fullfile(harmonicsDir, 'plm2xyz.m')
    fullfile(barystaticDir, 'IB.mat')
    fullfile(barystaticDir, 'ocean_mask', 'landmask_181361.mat')
};

missing = requiredFiles(~cellfun(@isfile, requiredFiles));
if ~isempty(missing)
    error('SLEBatch:MissingFile', 'Required file is missing:\n%s', ...
        strjoin(missing, newline));
end

% Put the pinned implementation ahead of any duplicate functions elsewhere
% on the user's MATLAB path.
addpath(harmonicsDir, '-begin');
addpath(sleDir, '-begin');
assert(strcmp(which('SLE'), fullfile(sleDir, 'SLE.m')), ...
    'The pinned SLE.m is not first on the MATLAB path.');

ibFile = fullfile(barystaticDir, 'IB.mat');
maskFile = fullfile(barystaticDir, 'ocean_mask', 'landmask_181361.mat');

ib = load(ibFile, 'IB_AIS', 'tv_r');
mask = load(maskFile, 'land');

assert(isfield(ib, 'IB_AIS') && isfield(ib, 'tv_r'), ...
    'IB.mat must contain IB_AIS and tv_r.');
assert(isequal(size(mask.land), size(ib.IB_AIS, [1 2])), ...
    'The land mask and IB_AIS horizontal grids do not match.');

ocean = ~logical(mask.land);
ais = double(ib.IB_AIS);
timeRaw = double(ib.tv_r);

% IB.mat currently stores MATLAB date vectors (year, month, day, ...),
% while some related files use a simple datenum vector. Accept both forms.
if ismatrix(timeRaw) && size(timeRaw, 2) == 6
    timeNum = datenum(timeRaw);
else
    timeNum = timeRaw(:);
end

if numel(timeNum) ~= size(ais, 3)
    error('SLEBatch:TimeMismatch', ...
        'tv_r length (%d) does not match IB_AIS months (%d).', ...
        numel(timeNum), size(ais, 3));
end

baselineStart = datenum(2003, 1, 1);
baselineEnd = datenum(2010, 12, 31);
baselineIndex = timeNum >= baselineStart & timeNum <= baselineEnd;
assert(any(baselineIndex), 'No IB_AIS months fall in the 2003-2010 baseline.');

baseline = mean(ais(:, :, baselineIndex), 3, 'omitnan');

% These dates span the start, middle, and end of the available AIS record.
requestedDates = datenum([2003 2010 2020], [1 12 12], [15 15 15]);
targetIndex = zeros(size(requestedDates));
for k = 1:numel(requestedDates)
    [distanceDays, targetIndex(k)] = min(abs(timeNum - requestedDates(k)));
    assert(distanceDays <= 20, ...
        'No monthly field was found near %s.', datestr(requestedDates(k), 'yyyy-mm'));
end

targetDates = timeNum(targetIndex);
nMonths = numel(targetIndex);
loading = zeros(size(ais, 1), size(ais, 2), nMonths);
for k = 1:nMonths
    monthLoading = ais(:, :, targetIndex(k)) - baseline;
    monthLoading(ocean) = 0;
    monthLoading(~isfinite(monthLoading)) = 0;
    loading(:, :, k) = monthLoading;
end

maxDegree = 60;

fprintf('\nSLE batch validation\n');
fprintf('Implementation : %s\n', which('SLE'));
fprintf('Maximum degree: N = %d\n', maxDegree);
fprintf('Baseline       : 2003-01 through 2010-12 mean\n');
fprintf('Target months  : %s\n\n', ...
    strjoin(cellstr(datestr(targetDates, 'yyyy-mm')), ', '));

%% Established serial calculation
salSerial = zeros(size(loading));
updateSerial = zeros(1, nMonths);
serialMonthSeconds = zeros(1, nMonths);

serialClock = tic;
for k = 1:nMonths
    monthClock = tic;
    [salSerial(:, :, k), updateSerial(k)] = ...
        SLE(ocean, 0, loading(:, :, k), maxDegree);
    serialMonthSeconds(k) = toc(monthClock);
end
serialSeconds = toc(serialClock);

%% Month-parallel calculation
parallelAvailable = license('test', 'Distrib_Computing_Toolbox') && ...
    ~isempty(ver('parallel'));

if parallelAvailable
    existingPool = gcp('nocreate');
    createdPool = isempty(existingPool);

    poolClock = tic;
    if createdPool
        localCluster = parcluster('local');
        workerCount = min(nMonths, localCluster.NumWorkers);
        pool = parpool('local', workerCount);
    else
        pool = existingPool;
    end
    poolStartupSeconds = toc(poolClock);

    salParallel = zeros(size(loading));
    updateParallel = zeros(1, nMonths);

    parallelClock = tic;
    parfor k = 1:nMonths
        % Workers can have a different MATLAB path from the client. Pin the
        % same implementation inside every independent monthly task.
        addpath(harmonicsDir, '-begin');
        addpath(sleDir, '-begin');
        [salParallel(:, :, k), updateParallel(k)] = ...
            SLE(ocean, 0, loading(:, :, k), maxDegree);
    end
    parallelSeconds = toc(parallelClock);
else
    pool = [];
    createdPool = false;
    poolStartupSeconds = NaN;
    parallelSeconds = NaN;
    salParallel = [];
    updateParallel = [];
end

%% Scientific and numerical checks
[longitude, colatitude] = size2sph(ocean);
cellArea = spheregrid(6371000, longitude, colatitude);
oceanArea = sum(cellArea(ocean), 'omitnan');

fprintf('Serial calculation: %.3f s total (%.3f s/month)\n', ...
    serialSeconds, serialSeconds / nMonths);

if parallelAvailable
    fprintf('Pool startup       : %.3f s (reported separately)\n', poolStartupSeconds);
    fprintf('Parallel calculation: %.3f s total (%.3f s/month equivalent)\n', ...
        parallelSeconds, parallelSeconds / nMonths);
    fprintf('Kernel speed-up    : %.2fx\n\n', serialSeconds / parallelSeconds);
else
    fprintf(['Parallel calculation skipped: Parallel Computing Toolbox ', ...
        'is not available.\n\n']);
end

fprintf(['Month    Input land  Output ocean  Residual     Ocean mean  ', ...
    'Update\n']);
fprintf(['         (Gt)        (Gt)          (Gt)         (mm)        ', ...
    '(mm)\n']);

maxMassResidualGt = 0;
maxMeanUpdateDifferenceMm = 0;
for k = 1:nMonths
    inputLandGt = sum(loading(:, :, k) .* cellArea, 'all', 'omitnan') / 1e12;
    outputOceanGt = sum(salSerial(:, :, k) .* cellArea .* 1000, ...
        'all', 'omitnan') / 1e12;
    massResidualGt = inputLandGt + outputOceanGt;
    oceanMeanMm = sum(salSerial(:, :, k) .* cellArea, ...
        'all', 'omitnan') / oceanArea * 1000;
    updateMm = updateSerial(k) * 1000;

    maxMassResidualGt = max(maxMassResidualGt, abs(massResidualGt));
    maxMeanUpdateDifferenceMm = max(maxMeanUpdateDifferenceMm, ...
        abs(oceanMeanMm - updateMm));

    fprintf('%s  %10.3f  %12.3f  %+10.3e  %10.5f  %10.5f\n', ...
        datestr(targetDates(k), 'yyyy-mm'), inputLandGt, outputOceanGt, ...
        massResidualGt, oceanMeanMm, updateMm);
end

fprintf('\nMaximum mass residual             : %.3e Gt\n', maxMassResidualGt);
fprintf('Maximum ocean-mean/update mismatch: %.3e mm\n', ...
    maxMeanUpdateDifferenceMm);

if parallelAvailable
    maxFieldDifferenceMm = max(abs(salSerial - salParallel), ...
        [], 'all', 'omitnan') * 1000;
    maxUpdateDifferenceMm = max(abs(updateSerial - updateParallel), ...
        [], 'omitnan') * 1000;

    fprintf('Maximum serial/parallel field difference : %.3e mm\n', ...
        maxFieldDifferenceMm);
    fprintf('Maximum serial/parallel update difference: %.3e mm\n', ...
        maxUpdateDifferenceMm);

    numericalToleranceMm = 1e-8;
    assert(maxFieldDifferenceMm < numericalToleranceMm, ...
        'Serial and parallel SLE fields differ beyond tolerance.');
    assert(maxUpdateDifferenceMm < numericalToleranceMm, ...
        'Serial and parallel updates differ beyond tolerance.');
end

assert(maxMassResidualGt < 1e-6, ...
    'SLE mass conservation residual exceeds tolerance.');
assert(maxMeanUpdateDifferenceMm < 1e-8, ...
    'Ocean-area mean and SLE update differ beyond tolerance.');

fprintf('\nPASS: three-month batch calculation is numerically consistent.\n');

% Do not close a pool that the user had already opened before this script.
if parallelAvailable && createdPool && ~isempty(pool)
    delete(pool);
end
