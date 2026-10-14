<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\PushRequest;
use App\Services\SyncService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class SyncController extends Controller
{
    public function __construct(private SyncService $sync) {}

    public function pull(Request $request): JsonResponse
    {
        $request->validate(['since' => ['nullable', 'integer', 'min:0']]);

        return response()->json($this->sync->pull($request->user(), $request->integer('since')));
    }

    public function push(PushRequest $request): JsonResponse
    {
        // input() y no validated(): validated() recortaría los campos de cada bloque.
        return response()->json($this->sync->push(
            $request->user(),
            $request->input('notebooks'),
            $request->input('notes'),
        ));
    }
}
