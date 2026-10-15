<?php

namespace App\Services;

use App\Models\Note;
use App\Models\Notebook;
use App\Models\User;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Facades\DB;

/**
 * Sincronización por cursor (`rev`) con resolución last-write-wins según `updated_at`.
 */
class SyncService
{
    public function currentRev(User $user): int
    {
        return (int) DB::table('sync_counters')->where('user_id', $user->id)->value('rev');
    }

    /**
     * Todo lo que cambió después de `$since`, lápidas incluidas.
     *
     * @return array{rev:int, notebooks:\Illuminate\Support\Collection, notes:\Illuminate\Support\Collection}
     */
    public function pull(User $user, int $since): array
    {
        return [
            'rev' => $this->currentRev($user),
            'notebooks' => Notebook::where('user_id', $user->id)->where('rev', '>', $since)->orderBy('rev')->get(),
            'notes' => Note::where('user_id', $user->id)->where('rev', '>', $since)->orderBy('rev')->get(),
        ];
    }

    /**
     * Aplica los cambios del cliente. Devuelve el `rev` resultante y los registros
     * rechazados porque la versión del servidor es más reciente (el cliente debe adoptarlos).
     *
     * @param  array<int, array<string, mixed>>  $notebooks
     * @param  array<int, array<string, mixed>>  $notes
     * @return array{rev:int, notebooks:array, notes:array}
     */
    public function push(User $user, array $notebooks, array $notes): array
    {
        return DB::transaction(function () use ($user, $notebooks, $notes) {
            DB::table('sync_counters')->insertOrIgnore(['user_id' => $user->id, 'rev' => 0]);
            $rev = $this->currentRev($user);

            $rejected = ['notebooks' => [], 'notes' => []];

            foreach ($notebooks as $data) {
                $attrs = [
                    'name' => $data['name'],
                    'sort' => $data['sort'] ?? 0,
                    'created_at' => $data['created_at'],
                    'updated_at' => $data['updated_at'],
                    'deleted_at' => $data['deleted_at'] ?? null,
                ];
                if ($loser = $this->upsert(Notebook::class, $user, $data['id'], $attrs, $rev)) {
                    $rejected['notebooks'][] = $loser;
                }
            }

            foreach ($notes as $data) {
                $attrs = [
                    'notebook_id' => $data['notebook_id'] ?? null,
                    'title' => $data['title'] ?? '',
                    'blocks' => $data['blocks'] ?? [],
                    'created_at' => $data['created_at'],
                    'updated_at' => $data['updated_at'],
                    'trashed_at' => $data['trashed_at'] ?? null,
                    'deleted_at' => $data['deleted_at'] ?? null,
                ];
                if ($loser = $this->upsert(Note::class, $user, $data['id'], $attrs, $rev)) {
                    $rejected['notes'][] = $loser;
                }
            }

            DB::table('sync_counters')->where('user_id', $user->id)->update(['rev' => $rev]);

            return ['rev' => $rev] + $rejected;
        });
    }

    /**
     * @param  class-string<Model>  $class
     * @return Model|null  el registro del servidor si el entrante perdió
     */
    private function upsert(string $class, User $user, string $id, array $attrs, int &$rev): ?Model
    {
        $existing = $class::find($id);

        if ($existing && $existing->user_id !== $user->id) {
            abort(409, 'ID en uso por otro usuario.');
        }

        if ($existing && $existing->updated_at > $attrs['updated_at']) {
            return $existing;
        }

        // Una lápida es definitiva: no se resucita un registro eliminado.
        if ($existing && $existing->deleted_at !== null && $attrs['deleted_at'] === null) {
            return $existing;
        }

        $model = $existing ?? new $class(['id' => $id, 'user_id' => $user->id]);
        $model->fill($attrs);
        $model->rev = ++$rev;
        $model->save();

        return null;
    }
}
